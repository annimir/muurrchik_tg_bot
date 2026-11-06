import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from telegram.error import TelegramError
from telegram.ext import ConversationHandler

from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class DatabaseIntegrationTests(PostgresTestCase):
    def test_ensure_user_is_idempotent(self):
        user = queries.ensure_user(100, 'first')

        updated = queries.ensure_user(100, 'updated')

        self.assertEqual(updated['id'], user['id'])
        self.assertEqual(updated['tag'], 'updated')
        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM users').one()['cnt'], 1)

    def test_primary_character_and_shared_position(self):
        user = queries.ensure_user(100, 'user')
        first = queries.create_character_row(user['id'], 'First', None, None, None, True)
        second = queries.create_character_row(user['id'], 'Second', None, None, None, False)

        queries.set_character_primary(user['id'], second['id'])
        position_id = queries.add_position('Leader')
        queries.assign_position_to_character(first['id'], position_id)
        queries.assign_position_to_character(second['id'], position_id)

        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM character WHERE is_primary').one()['cnt'], 1)
        self.assertTrue(queries.get_character_by_id(second['id'])['is_primary'])
        self.assertEqual(queries.get_character_by_id(first['id'])['position_id'], position_id)
        self.assertEqual(queries.get_character_by_id(second['id'])['position_id'], position_id)

    def test_request_claim_and_approval_are_atomic(self):
        user = queries.ensure_user(100, 'user')
        request_id = queries.create_character_request('create', user['id'], 100, name='Character')

        self.assertTrue(queries.claim_request('character', request_id, 1000))
        self.assertFalse(queries.claim_request('character', request_id, 2000))
        result = queries.approve_character_create_request(request_id)

        self.assertEqual(result['character']['name'], 'Character')
        self.assertEqual(result['created_tag']['name'], 'Character')
        self.assertEqual(
            queries.db('SELECT status FROM character_requests WHERE id = %s', (request_id,)).one()['status'],
            'approved',
        )

    def test_card_approval(self):
        user = queries.ensure_user(100, 'user')
        request_id = queries.create_card_request(user['id'], 100, 'bio')

        self.assertEqual(queries.approve_card_request(request_id)['bio'], 'bio')
        self.assertIsNone(queries.approve_card_request(request_id))
        self.assertEqual(queries.db('SELECT bio FROM user_card WHERE user_id = %s', (user['id'],)).one()['bio'], 'bio')

    def test_transaction_rolls_back_on_error(self):
        with self.assertRaises(RuntimeError):
            with queries.db.transaction() as tx:
                tx("INSERT INTO games (code, name) VALUES ('rollback', 'Rollback')").close()
                raise RuntimeError('rollback')

        self.assertIsNone(queries.db("SELECT 1 FROM games WHERE code = 'rollback'").one())


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class HandlerIntegrationTests(PostgresTestCase):
    async def test_language_command_creates_missing_user(self):
        from handlers.users.language import language_command

        reply = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=100, username='new_user'),
            effective_message=SimpleNamespace(reply_text=reply, message_thread_id=None),
        )
        context = SimpleNamespace(args=['EN'])

        await language_command(update, context)

        self.assertEqual(queries.get_user_language(100), 'EN')
        reply.assert_awaited_once()

    async def test_tagstats_supports_edited_message(self):
        from handlers.tags.stats import tagstats_command

        queries.create_tag('Tag')
        reply = AsyncMock()
        update = SimpleNamespace(
            message=None,
            edited_message=object(),
            effective_user=SimpleNamespace(id=100),
            effective_message=SimpleNamespace(reply_text=reply, message_thread_id=None),
        )
        context = SimpleNamespace(args=['Tag'])

        await tagstats_command(update, context)

        reply.assert_awaited_once()

    async def test_tag_suggestion_with_percent_does_not_crash(self):
        from handlers.tags.tagging import resolve_tag_subscribers

        queries.create_tag('еимия')
        reply = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=100),
            effective_message=SimpleNamespace(message_thread_id=None, reply_text=reply),
        )
        context = SimpleNamespace(user_data={})
        suggestion = {'status': 'suggest', 'tag': 'еимия', 'score': 66.66666666666667}

        with patch('handlers.tags.tagging.tag_storage.find', return_value=suggestion):
            result = await resolve_tag_subscribers(update, context, 'митя')

        self.assertIsNone(result)
        reply.assert_awaited_once()
        self.assertIn('67%', reply.await_args.args[0])
        self.assertEqual(context.user_data['pending_new_tag'], 'митя')

    async def test_character_request_creates_missing_user(self):
        from handlers.characters.requests import ask_photo

        reply = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=100, username='new_user', full_name='New User'),
            effective_message=SimpleNamespace(
                photo=[SimpleNamespace(file_id='photo')], reply_text=reply,
            ),
        )
        context = SimpleNamespace(user_data={
            'charreq': {
                'origin_chat_id': 100,
                'name': 'Character',
                'birth_date': None,
                'description': 'Description',
            }
        })

        with patch('handlers.characters.requests.notify_admin_new_character_request', new=AsyncMock()):
            state = await ask_photo(update, context)

        self.assertEqual(state, ConversationHandler.END)
        self.assertIsNotNone(queries.get_user_by_tg_id(100))
        self.assertEqual(len(queries.get_user_character_requests(1)), 1)

    async def test_rich_card_sends_buttons_and_full_description(self):
        from handlers.cards.view import card_command, show_card_description

        user = queries.ensure_user(100, 'player')
        player_bio = 'Player biography. ' + 'Дополнительные сведения об игроке. ' * 12 + 'Конец биографии игрока.'
        queries.upsert_user_card_bio(user['id'], player_bio)
        queries.db(
            "UPDATE users SET chat_position = 'Модератор' WHERE id = %s",
            (user['id'],),
        ).close()
        queries.db(
            'INSERT INTO user_titles (user_id, name) VALUES (%s, %s)',
            (user['id'], 'Архивариус'),
        ).close()
        queries.set_birthday(100, 'player', 5, 2, 2000)
        queries.db("INSERT INTO games (code, name) VALUES ('genshin', 'Genshin Impact')").close()
        queries.db("INSERT INTO user_games (user_id, game_code) VALUES (%s, 'genshin')", (user['id'],)).close()
        position_id = queries.add_position('Архонт')
        description = f'Начало <b> {"длинное описание " * 500} конец'
        character = queries.create_character_row(user['id'], 'Фокалорс', None, 'photo-id', description, True)
        queries.db(
            '''
            UPDATE character SET wiki_url = 'https://wiki.example/character',
                birth_date = '2001-02-03' WHERE id = %s
            ''',
            (character['id'],),
        ).close()
        queries.assign_position_to_character(character['id'], position_id)
        secondary = queries.create_character_row(user['id'], 'Керидра', None, None, None, False)
        queries.create_tag('Фокалорс')
        furina_tag = queries.create_tag('Фурина')
        queries.db(
            "INSERT INTO tag_alias (tag_id, alias) VALUES (%s, 'Фокалорс'), (%s, 'Фурина лучшая')",
            (furina_tag['id'], furina_tag['id']),
        ).close()
        fatui_id = queries.add_affiliation('Фатуи')
        harbinger_id = queries.add_affiliation('Предвестник', fatui_id)
        queries.assign_affiliation_to_character(character['id'], fatui_id)
        queries.db(
            'INSERT INTO character_affiliation (character_id, affiliation_id) VALUES (%s, %s)',
            (character['id'], harbinger_id),
        ).close()

        reply_photo = AsyncMock()
        reply_text = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=100, full_name='Player'),
            effective_message=SimpleNamespace(
                message_thread_id=None, reply_photo=reply_photo, reply_text=reply_text,
            ),
        )
        await card_command(update, SimpleNamespace(args=[]))

        reply_photo.assert_awaited_once()
        reply_text.assert_not_awaited()
        caption = reply_photo.await_args.kwargs['caption']
        self.assertLessEqual(len(caption), 1024)
        self.assertIn('<b>ФОКАЛОРС</b> | Модератор\n@player', caption)
        self.assertNotIn('\n\n@player\n\n', caption)
        self.assertNotIn('Player\n', caption)
        self.assertIn('🏅 Титулы: Архивариус', caption)
        self.assertIn('День рождения: 05.02', caption)
        self.assertNotIn('05.02.2000', caption)
        self.assertNotIn('День рождения персонажа:', caption)
        self.assertNotIn('Теги и алиасы:', caption)
        self.assertIn('Другие персонажи: Керидра', caption)
        self.assertIn('🎮 Игры: Genshin Impact', caption)
        self.assertIn('🏛️ Принадлежность: Предвестник, Фатуи', caption)
        self.assertIn('&lt;b&gt;', caption)
        self.assertIn(player_bio, caption)
        self.assertGreater(len(player_bio), 240)
        buttons = [
            button
            for row in reply_photo.await_args.kwargs['reply_markup'].inline_keyboard
            for button in row
        ]
        self.assertEqual(buttons[0].url, f'http://testserver/users/{user["id"]}')
        self.assertEqual(buttons[1].callback_data, f'cardchar:{user["id"]}:{character["id"]}')
        self.assertEqual(buttons[2].callback_data, f'cardchar:{user["id"]}:{secondary["id"]}')

        edit_media = AsyncMock()
        edit_text = AsyncMock()
        query = SimpleNamespace(
            data=f'cardchar:{user["id"]}:{secondary["id"]}',
            from_user=SimpleNamespace(id=100),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=200), message_thread_id=None, photo=[object()],
            ),
            answer=AsyncMock(),
            edit_message_media=edit_media,
            edit_message_text=edit_text,
        )
        context = SimpleNamespace()
        await show_card_description(SimpleNamespace(callback_query=query), context)

        query.answer.assert_awaited_once()
        edit_media.assert_awaited_once()
        edit_text.assert_not_awaited()
        media = edit_media.await_args.kwargs['media']
        from telegram import InputFile
        from handlers.cards.view import CARD_PLACEHOLDER

        self.assertIsInstance(media.media, InputFile)
        self.assertIsNotNone(media.media.attach_name)
        self.assertEqual(media.media.filename, 'card-placeholder.png')
        self.assertEqual(media.media.input_file_content, CARD_PLACEHOLDER.read_bytes())
        self.assertIn('<b>КЕРИДРА</b>', media.caption)
        back_button = edit_media.await_args.kwargs['reply_markup'].inline_keyboard[1][0]
        self.assertEqual(back_button.callback_data, f'cardplayer:{user["id"]}')

        query.data = f'cardchar:{user["id"]}:{character["id"]}'
        await show_card_description(SimpleNamespace(callback_query=query), context)
        first_page = edit_media.await_args.kwargs['media'].caption
        self.assertIn('<b>ФОКАЛОРС</b>', first_page)
        self.assertIn('Архонт', first_page)
        self.assertIn('День рождения персонажа: 03.02', first_page)
        self.assertNotIn('03.02.2001', first_page)
        self.assertIn('Теги и алиасы: #Фокалорс, #Фурина, #Фурина лучшая', first_page)
        self.assertIn('&lt;b&gt;', first_page)
        self.assertLessEqual(len(first_page), 1024)
        markup = edit_media.await_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].url, f'http://testserver/characters/{character["id"]}')
        self.assertEqual(markup.inline_keyboard[0][1].url, 'https://wiki.example/character')
        self.assertEqual(markup.inline_keyboard[1][0].callback_data, f'cardplayer:{user["id"]}')
        self.assertEqual(
            markup.inline_keyboard[2][0].callback_data,
            f'cardchar:{user["id"]}:{character["id"]}:1',
        )

        query.data = f'cardchar:{user["id"]}:{character["id"]}:1'
        await show_card_description(SimpleNamespace(callback_query=query), context)
        self.assertEqual(edit_media.await_count, 3)
        self.assertLessEqual(len(edit_media.await_args.kwargs['media'].caption), 1024)
        query.data = f'cardplayer:{user["id"]}'
        await show_card_description(SimpleNamespace(callback_query=query), context)
        player_caption = edit_media.await_args.kwargs['media'].caption
        self.assertIn('Другие персонажи: Керидра', player_caption)
        self.assertIn('🎮 Игры: Genshin Impact', player_caption)
        self.assertLessEqual(len(player_caption), 1024)

    async def test_card_without_characters_shows_player_profile(self):
        from handlers.cards.view import card_command

        user = queries.ensure_user(100, 'player')
        queries.db(
            "UPDATE users SET avatar_file_id = 'avatar-file', chat_position = 'Модератор' WHERE id = %s",
            (user['id'],),
        ).close()
        queries.db(
            'INSERT INTO user_titles (user_id, name) VALUES (%s, %s)',
            (user['id'], 'Архивариус'),
        ).close()
        queries.upsert_user_card_bio(user['id'], 'Player biography')
        reply_photo = AsyncMock()
        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=999, full_name='Requester'),
            effective_message=SimpleNamespace(
                message_thread_id=None, reply_photo=reply_photo, reply_text=AsyncMock(),
            ),
        )

        await card_command(update, SimpleNamespace(args=['@player']))

        caption = reply_photo.await_args.kwargs['caption']
        self.assertEqual(reply_photo.await_args.kwargs['photo'], 'avatar-file')
        self.assertIn('<b>@player</b>', caption)
        self.assertIn('🏅 Титулы: Архивариус', caption)
        self.assertNotIn('Модератор', caption)
        self.assertIn('Player biography', caption)
        buttons = [
            button
            for row in reply_photo.await_args.kwargs['reply_markup'].inline_keyboard
            for button in row
        ]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].url, f'http://testserver/users/{user["id"]}')

    async def test_retention_marks_warning_only_after_delivery(self):
        from handlers.jobs.retention import send_retention_warnings

        user = queries.ensure_user(100, 'user')
        queries.db("UPDATE users SET left_at = now() - interval '7 months'").close()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(side_effect=TelegramError('failed'))))

        await send_retention_warnings(context)
        self.assertIsNone(queries.get_user_by_id(user['id'])['deletion_warned_at'])

        context.bot.send_message = AsyncMock()
        await send_retention_warnings(context)
        self.assertIsNotNone(queries.get_user_by_id(user['id'])['deletion_warned_at'])

    async def test_video_link_with_hashtag_notifies_subscribers(self):
        from handlers.tags.tagging import link_tag_handler

        user = queries.ensure_user(100, 'user')
        tag = queries.create_tag('videos')
        queries.subscribe_tag(user['tg_id'], tag['id'])

        for url in (
            'https://youtu.be/video-id',
            'https://www.instagram.com/reel/video-id/',
            'https://www.tiktok.com/@user/video/123',
        ):
            with self.subTest(url=url):
                send_message = AsyncMock()
                update = SimpleNamespace(
                    edited_message=None,
                    effective_user=SimpleNamespace(id=100),
                    effective_chat=SimpleNamespace(id=200),
                    effective_message=SimpleNamespace(
                        text=f'Смотрите {url} #videos',
                        via_bot=False,
                        forward_origin=None,
                        message_thread_id=None,
                        message_id=1,
                    ),
                )
                context = SimpleNamespace(
                    user_data={}, bot=SimpleNamespace(send_message=send_message),
                )

                await link_tag_handler(update, context)

                send_message.assert_awaited_once()
                self.assertIn('tg://user?id=100', send_message.await_args.kwargs['text'])

    async def test_video_link_handler_requires_link_and_hashtag(self):
        from handlers.tags.tagging import link_tag_handler

        send_message = AsyncMock()
        update = SimpleNamespace(
            edited_message=None,
            effective_user=SimpleNamespace(id=100),
            effective_chat=SimpleNamespace(id=200),
            effective_message=SimpleNamespace(
                text='Текст без ссылки #videos',
                via_bot=False,
                forward_origin=None,
                message_thread_id=None,
                message_id=1,
            ),
        )
        context = SimpleNamespace(
            user_data={}, bot=SimpleNamespace(send_message=send_message),
        )

        await link_tag_handler(update, context)
        update.effective_message.text = 'https://youtu.be/video-id'
        await link_tag_handler(update, context)

        send_message.assert_not_awaited()

    async def test_media_group_tags_every_photo_regardless_of_caption_position(self):
        import asyncio
        from handlers.tags import tagging
        from web.queries import list_media

        user = queries.ensure_user(100, 'user')
        tag = queries.create_tag('album-photos')
        queries.subscribe_tag(user['tg_id'], tag['id'])

        def media_update(message_id, group_id, caption):
            return SimpleNamespace(
                edited_message=None,
                effective_user=SimpleNamespace(id=100),
                effective_chat=SimpleNamespace(id=200),
                effective_message=SimpleNamespace(
                    message_id=message_id,
                    message_thread_id=None,
                    media_group_id=group_id,
                    caption=caption,
                    via_bot=False,
                    forward_origin=None,
                    photo=[SimpleNamespace(
                        file_id=f'file-{group_id}-{message_id}',
                        file_unique_id=f'unique-{group_id}-{message_id}',
                    )],
                    video=None,
                    reply_text=AsyncMock(),
                ),
            )

        for caption_index in range(3):
            with self.subTest(caption_index=caption_index):
                queries.db('DELETE FROM tag_usage').close()
                context = SimpleNamespace(
                    user_data={}, bot_data={},
                    bot=SimpleNamespace(send_message=AsyncMock()),
                )
                group_id = f'album-{caption_index}'
                updates = [
                    media_update(index + 1, group_id, '#album-photos' if index == caption_index else None)
                    for index in range(3)
                ]

                with patch.object(tagging, 'MEDIA_GROUP_DELAY', 0):
                    for update in updates:
                        await tagging.media_tag_handler(update, context)
                    await asyncio.sleep(0.01)

                rows = queries.db(
                    'SELECT * FROM tag_usage ORDER BY telegram_message_id'
                ).all()
                self.assertEqual(len(rows), 3)
                self.assertEqual(
                    [row['media_file_unique_id'] for row in rows],
                    [f'unique-{group_id}-{index}' for index in range(1, 4)],
                )
                self.assertEqual(len(list_media(limit=24)), 3)
                context.bot.send_message.assert_awaited_once()
                self.assertEqual(context.bot_data[tagging.MEDIA_GROUPS_KEY], {})

    async def test_tag_suggestion_choices_subscribe_and_log_media(self):
        from handlers.tags.callbacks import callback_router
        from handlers.tags.tagging import create_yes_no_markup

        queries.ensure_user(100, 'user')
        existing = queries.create_tag('Арлекино')
        markup = create_yes_no_markup(existing['id'], 100, 'RU', 'Арлекино', 'Арлекииино')
        self.assertEqual(markup.inline_keyboard[0][0].text, 'Да, использовать #Арлекино')
        self.assertEqual(markup.inline_keyboard[1][0].text, 'Создать #Арлекииино и подписаться')

        def media_update(message_id):
            return SimpleNamespace(
                effective_chat=SimpleNamespace(id=200),
                effective_message=SimpleNamespace(
                    message_id=message_id, message_thread_id=None,
                    caption='#Арлекииино', text=None,
                    photo=[SimpleNamespace(
                        file_id=f'file-{message_id}', file_unique_id=f'unique-{message_id}',
                    )],
                    video=None,
                ),
            )

        def callback(data):
            return SimpleNamespace(
                data=data,
                from_user=SimpleNamespace(id=100, username='user'),
                message=SimpleNamespace(
                    chat=SimpleNamespace(id=200), message_thread_id=None, message_id=500,
                ),
                answer=AsyncMock(),
            )

        def context():
            return SimpleNamespace(
                user_data={
                    'pending_new_tag': 'Арлекииино',
                    'pending_tag_usage': [(media_update(1), 'photo'), (media_update(2), 'photo')],
                },
                bot=SimpleNamespace(send_message=AsyncMock(), delete_message=AsyncMock()),
            )

        accept_context = context()
        await callback_router(SimpleNamespace(callback_query=callback(
            f'tag/{existing["id"]}/100',
        )), accept_context)

        accepted_rows = queries.db('SELECT * FROM tag_usage ORDER BY telegram_message_id').all()
        self.assertEqual(len(accepted_rows), 2)
        self.assertTrue(all(row['tag_id'] == existing['id'] for row in accepted_rows))
        self.assertEqual(queries.get_user_subscriptions(100), [])
        self.assertNotIn('pending_new_tag', accept_context.user_data)
        self.assertNotIn('pending_tag_usage', accept_context.user_data)

        queries.db('DELETE FROM tag_usage').close()
        create_context = context()
        create_context.user_data['pending_tag_usage'] = [(media_update(3), 'photo')]
        await callback_router(
            SimpleNamespace(callback_query=callback('new/100')), create_context,
        )

        created = queries.get_tag_by_name('Арлекииино')
        self.assertIsNotNone(created)
        self.assertEqual(
            [row['name'] for row in queries.get_user_subscriptions(100)], ['Арлекииино'],
        )
        created_usage = queries.db('SELECT * FROM tag_usage').one()
        self.assertEqual(created_usage['tag_id'], created['id'])
        self.assertEqual(created_usage['media_file_unique_id'], 'unique-3')
        self.assertIn('подписались', create_context.bot.send_message.await_args.args[1])

    def test_callback_data_uses_tag_id(self):
        from handlers.tags.tagging import create_subscribe_markup

        subscribe_button, cancel_button = create_subscribe_markup(123).inline_keyboard[0]

        self.assertEqual(subscribe_button.callback_data, 'subscribe/123')
        self.assertLessEqual(len(subscribe_button.callback_data.encode()), 64)
        self.assertEqual(cancel_button.text, 'Отмена')
        self.assertEqual(cancel_button.callback_data, 'cancel')

    async def test_cancel_subscription_prompt_deletes_message(self):
        from handlers.tags.callbacks import callback_router

        queries.ensure_user(100, 'user')
        delete_message = AsyncMock()
        call = SimpleNamespace(
            data='cancel',
            from_user=SimpleNamespace(id=100, username='user'),
            message=SimpleNamespace(
                chat=SimpleNamespace(id=200), message_thread_id=None, message_id=500,
            ),
            answer=AsyncMock(),
        )
        context = SimpleNamespace(bot=SimpleNamespace(delete_message=delete_message))

        await callback_router(SimpleNamespace(callback_query=call), context)

        delete_message.assert_awaited_once_with(200, 500)
