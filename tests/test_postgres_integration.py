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

    def test_primary_character_and_position_transfer(self):
        user = queries.ensure_user(100, 'user')
        first = queries.create_character_row(user['id'], 'First', None, None, None, True)
        second = queries.create_character_row(user['id'], 'Second', None, None, None, False)

        queries.set_character_primary(user['id'], second['id'])
        position_id = queries.add_position('Leader')
        queries.assign_position_to_character(first['id'], position_id)
        queries.assign_position_to_character(second['id'], position_id)

        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM character WHERE is_primary').one()['cnt'], 1)
        self.assertTrue(queries.get_character_by_id(second['id'])['is_primary'])
        self.assertIsNone(queries.get_character_by_id(first['id'])['position_id'])
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
        from handlers.language import language_command

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
        from handlers.tag_stats import tagstats_command

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

    async def test_character_request_creates_missing_user(self):
        from handlers.character_requests import ask_photo

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

        with patch('handlers.character_requests.notify_admin_new_character_request', new=AsyncMock()):
            state = await ask_photo(update, context)

        self.assertEqual(state, ConversationHandler.END)
        self.assertIsNotNone(queries.get_user_by_tg_id(100))
        self.assertEqual(len(queries.get_user_character_requests(1)), 1)

    async def test_retention_marks_warning_only_after_delivery(self):
        from handlers.retention_job import send_retention_warnings

        user = queries.ensure_user(100, 'user')
        queries.db("UPDATE users SET left_at = now() - interval '7 months'").close()
        context = SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock(side_effect=TelegramError('failed'))))

        await send_retention_warnings(context)
        self.assertIsNone(queries.get_user_by_id(user['id'])['deletion_warned_at'])

        context.bot.send_message = AsyncMock()
        await send_retention_warnings(context)
        self.assertIsNotNone(queries.get_user_by_id(user['id'])['deletion_warned_at'])

    async def test_video_link_with_hashtag_notifies_subscribers(self):
        from handlers.tagging import link_tag_handler

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
        from handlers.tagging import link_tag_handler

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

    def test_callback_data_uses_tag_id(self):
        from handlers.tagging import create_subscribe_markup

        button = create_subscribe_markup(123).inline_keyboard[0][0]

        self.assertEqual(button.callback_data, 'subscribe/123')
        self.assertLessEqual(len(button.callback_data.encode()), 64)
