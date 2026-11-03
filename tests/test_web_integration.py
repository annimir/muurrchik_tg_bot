import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import Response
from fastapi.testclient import TestClient

from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class WebIntegrationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        from web.app import create_app

        self.client = TestClient(create_app())

    def tearDown(self):
        self.client.close()

    def admin_session(self):
        from web.auth import SESSION_COOKIE, create_admin_session

        queries.add_admin(100)
        token, csrf = create_admin_session(100)
        self.client.cookies.set(SESSION_COOKIE, token)
        return csrf

    def test_public_pages_and_media_filters(self):
        user = queries.ensure_user(100, 'player')
        queries.create_character_row(user['id'], 'Hero', None, None, 'Description', True)
        tag = queries.create_tag('adventure')
        caption = 'Forest photo #adventure #forest'
        queries.log_tag_usage(
            tag['id'], 10, 100, 'photo', chat_id=200,
            media_file_id='photo-file', media_file_unique_id='photo-unique', caption=caption,
        )
        second_tag = queries.create_tag('forest')
        queries.log_tag_usage(
            second_tag['id'], 10, 100, 'photo', chat_id=200,
            media_file_id='photo-file', media_file_unique_id='photo-unique', caption=caption,
        )
        queries.log_tag_usage(
            tag['id'], 13, 100, 'photo', chat_id=200,
            media_file_id='photo-file', media_file_unique_id='photo-unique', caption=caption,
        )
        queries.log_tag_usage(
            tag['id'], 11, 100, 'video_link', chat_id=200,
            media_url='https://youtu.be/video-id', caption='Video link',
        )
        queries.log_tag_usage(
            tag['id'], 12, 100, 'video', chat_id=200,
            media_file_id='video-file', media_file_unique_id='video-unique', caption='Muted video',
        )

        home = self.client.get('/')
        catalog = self.client.get('/media?kind=photo')
        multiple_tags = self.client.get(f'/media?tag={tag["id"]}&tag={second_tag["id"]}')
        single_tag = self.client.get(f'/media?tag={second_tag["id"]}')
        multiple_kinds = self.client.get('/media?kind=photo&kind=video')
        multiple_sorts = self.client.get('/media?sort=oldest&sort=tag')
        empty_filters = self.client.get('/media?tag=&kind=&date_from=&date_to=')
        today = date.today().isoformat()
        dated = self.client.get(f'/media?date_from={today}&date_to={today}')
        outside = self.client.get('/media?date_to=2000-01-01')
        characters = self.client.get('/characters')

        self.assertEqual(home.status_code, 200)
        self.assertIn('Летопись', home.text)
        self.assertIn('muted playsinline', home.text)
        self.assertIn('data-media-open=', home.text)
        self.assertIn(f'href="/media?tag={tag["id"]}&amp;sort=newest"', home.text)
        self.assertIn('Forest photo', catalog.text)
        self.assertIn('>adventure</a>', catalog.text)
        self.assertIn('>forest</a>', catalog.text)
        self.assertEqual(catalog.text.count('>adventure</a>'), 1)
        self.assertIn(
            f'href="/media?tag={tag["id"]}&amp;kind=photo&amp;sort=newest"', catalog.text,
        )
        self.assertNotIn('#adventure', catalog.text)
        self.assertNotIn('#forest', catalog.text)
        self.assertNotIn('Найти тег', catalog.text)
        self.assertIn('data-tag-search', catalog.text)
        self.assertIn('data-tag-name="adventure"', catalog.text)
        self.assertIn('data-filter-dropdown', catalog.text)
        self.assertIn('Автор:', catalog.text)
        self.assertIn('player', catalog.text)
        self.assertNotIn('Video link', catalog.text)
        self.assertIn('Forest photo', multiple_tags.text)
        self.assertIn('Video link', multiple_tags.text)
        self.assertIn(f'value="{tag["id"]}" checked', multiple_tags.text)
        self.assertIn(f'value="{second_tag["id"]}" checked', multiple_tags.text)
        self.assertIn('Forest photo', single_tag.text)
        self.assertNotIn('Video link', single_tag.text)
        self.assertIn('Forest photo', multiple_kinds.text)
        self.assertIn('Muted video', multiple_kinds.text)
        self.assertNotIn('Video link', multiple_kinds.text)
        self.assertIn('name="kind" value="photo" checked', multiple_kinds.text)
        self.assertIn('name="kind" value="video" checked', multiple_kinds.text)
        self.assertEqual(multiple_sorts.status_code, 200)
        self.assertIn('name="sort" value="oldest" checked', multiple_sorts.text)
        self.assertIn('name="sort" value="tag" checked', multiple_sorts.text)
        self.assertEqual(empty_filters.status_code, 200)
        self.assertEqual(self.client.get('/media?tag=unknown').status_code, 400)
        self.assertEqual(self.client.get('/media?tag=0').status_code, 400)
        self.assertEqual(self.client.get('/media?kind=unknown').status_code, 400)
        self.assertEqual(self.client.get('/media?sort=unknown').status_code, 400)
        self.assertIn('Forest photo', dated.text)
        self.assertIn('Video link', dated.text)
        self.assertIn('Muted video', dated.text)
        self.assertNotIn('Forest photo', outside.text)
        self.assertIn('Hero', characters.text)

    def test_media_tag_filter_sorts_latin_then_cyrillic(self):
        for name in ('яблоко', 'Zulu', 'Арбуз', 'alpha'):
            queries.create_tag(name)

        response = self.client.get('/media')

        self.assertEqual(response.status_code, 200)
        positions = [response.text.index(f'data-tag-name="{name}"') for name in ('alpha', 'zulu', 'арбуз', 'яблоко')]
        self.assertEqual(positions, sorted(positions))

    def test_used_tags_come_first_in_filter_and_search(self):
        tags = {}
        for name in ('alpha', 'apple', 'apricot', 'банан'):
            tags[name] = queries.create_tag(name)
        for index, name in enumerate(('apple', 'банан'), start=1):
            queries.log_tag_usage(
                tags[name]['id'], index, 100, 'photo', chat_id=200,
                media_file_id=f'file-{index}', media_file_unique_id=f'unique-{index}',
            )

        response = self.client.get('/media')
        search = self.client.get('/tags/search?q=a')

        ordered_names = ('apple', 'банан', 'alpha', 'apricot')
        positions = [response.text.index(f'data-tag-name="{name}"') for name in ordered_names]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(
            [tag['name'] for tag in search.json()['tags']], ['apple', 'alpha', 'apricot'],
        )

    def test_tag_search_uses_indexed_case_insensitive_prefix(self):
        for name in ('Алиса', 'Арлекино', 'Алина', 'Борис', 'Мария', 'Самовар', 'alpha', 'ALINA'):
            queries.create_tag(name)
        inactive = queries.create_tag('Автомат')
        queries.db("UPDATE tag SET status = 'DELETED' WHERE id = %s", (inactive['id'],)).close()

        russian = self.client.get('/tags/search?q=а')
        english = self.client.get('/tags/search?q=AL')
        middle = self.client.get('/tags/search?q=ма')
        wildcard = self.client.get('/tags/search?q=%25')

        self.assertEqual(russian.status_code, 200)
        self.assertEqual(
            {tag['name'].casefold() for tag in russian.json()['tags']},
            {'алиса', 'арлекино', 'алина'},
        )
        self.assertEqual({tag['name'].casefold() for tag in english.json()['tags']}, {'alpha', 'alina'})
        self.assertEqual([tag['name'].casefold() for tag in middle.json()['tags']], ['мария'])
        self.assertEqual(wildcard.json()['tags'], [])
        self.assertTrue(queries.db(
            "SELECT 1 AS present FROM pg_indexes WHERE indexname = 'tag_active_name_lower_prefix_idx'",
        ).one()['present'])

    def test_lore_categories_and_chronology(self):
        all_events = self.client.get('/lore')
        genshin = self.client.get('/lore?game=genshin')
        hsr = self.client.get('/lore?game=hsr')
        zzz = self.client.get('/lore?game=zzz')

        self.assertEqual(all_events.status_code, 200)
        self.assertIn('href="/lore"', all_events.text)
        self.assertIn('Genshin Impact', all_events.text)
        self.assertIn('HSR', all_events.text)
        self.assertIn('ZZZ', all_events.text)
        self.assertEqual(all_events.text.count('class="lore-event"'), 91)
        self.assertEqual(genshin.text.count('class="lore-event"'), 32)
        self.assertIn('32 событий', all_events.text)
        self.assertEqual(hsr.text.count('class="lore-event"'), 31)
        self.assertEqual(zzz.text.count('class="lore-event"'), 28)
        self.assertIn('Кто съел коней Варки', genshin.text)
        self.assertIn('Genshin — реклама Яндекса', genshin.text)
        self.assertNotIn('Хорни-экспресс получил бухгалтерию', genshin.text)
        self.assertIn('Билд Блейда без Блейда', hsr.text)
        self.assertIn('Пять Банбу в одном предвестнике', zzz.text)
        self.assertIn('https://t.me/c/1825070005/389499', genshin.text)
        self.assertLess(all_events.text.index('Фурина C2'), all_events.text.index('Гарант ушёл не в тот баннер'))
        self.assertLess(all_events.text.index('Секретный квест'), all_events.text.index('Чаепитие, предсказанное чатом'))
        self.assertEqual(self.client.get('/lore?game=unknown').status_code, 404)

    def test_paimon_commands_page_lists_groups_and_search(self):
        from web.commands import get_paimon_command_count

        response = self.client.get('/commands')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Команды Паймон', response.text)
        self.assertIn('href="/commands"', response.text)
        self.assertIn('class="active" href="/commands"', response.text)
        self.assertIn('/card [@username]', response.text)
        self.assertIn('/sub &lt;тег&gt;', response.text)
        self.assertIn('/newcharacter', response.text)
        self.assertIn('/assign_position', response.text)
        self.assertIn('Только для администраторов', response.text)
        self.assertIn('data-command-search', response.text)
        self.assertIn('data-commands-empty', response.text)
        self.assertEqual(response.text.count('data-command-card'), get_paimon_command_count())
        self.assertNotIn('/add_role', response.text)

    def test_chat_insights_page_and_periods(self):
        all_periods = self.client.get('/insights')
        year = self.client.get('/insights?period=2025')

        self.assertEqual(all_periods.status_code, 200)
        self.assertIn('Семантическая карта', all_periods.text)
        self.assertIn('data-word-cloud', all_periods.text)
        self.assertIn('data-semantic-map', all_periods.text)
        self.assertIn('/static/insights.js', all_periods.text)
        self.assertIn('href="/insights?period=2025"', all_periods.text)
        self.assertNotIn('result.json', all_periods.text)
        self.assertEqual(year.status_code, 200)
        self.assertIn('aria-current="page">2025</a>', year.text)
        self.assertEqual(self.client.get('/insights?period=unknown').status_code, 404)

    def test_user_profile_lists_only_active_subscriptions(self):
        user = queries.ensure_user(100, 'player')
        active_tag = queries.create_tag('active-subscription')
        inactive_tag = queries.create_tag('inactive-subscription')
        queries.subscribe_tag(100, active_tag['id'])
        queries.subscribe_tag(100, inactive_tag['id'])
        queries.unsubscribe_tag(100, inactive_tag['id'])

        response = self.client.get(f'/users/{user["id"]}')

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'href="/media?tag={active_tag["id"]}">active-subscription</a>', response.text)
        self.assertNotIn('inactive-subscription', response.text)

    def test_admin_requires_telegram_session_and_csrf(self):
        response = self.client.get('/admin', follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        csrf = self.admin_session()
        response = self.client.post('/admin/positions', data={'name': 'Position', 'csrf_token': csrf + 'bad'})
        self.assertEqual(response.status_code, 403)

    def test_admin_dashboard_renders(self):
        self.admin_session()
        queries.ensure_user(100, 'first')
        queries.ensure_user(200, 'second')
        tag = queries.create_tag('daily')
        inactive_tag = queries.create_tag('inactive')
        queries.log_tag_usage(tag['id'], 10, 100, 'photo')
        queries.subscribe_tag(100, tag['id'])
        queries.subscribe_tag(200, tag['id'])
        queries.subscribe_tag(100, inactive_tag['id'])
        queries.unsubscribe_tag(100, inactive_tag['id'])

        response = self.client.get('/admin')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Статистика сообщества', response.text)
        self.assertIn('Использование тегов', response.text)
        self.assertIn('За две недели', response.text)
        self.assertIn('Популярность тегов среди подписок', response.text)
        self.assertIn('<text class="pie-chart-total" x="21" y="21">2</text>', response.text)
        self.assertIn('>daily</a>', response.text)
        self.assertNotIn('#daily', response.text)
        self.assertNotIn('inactive', response.text)

    def test_admin_tag_usage_period_filters(self):
        self.admin_session()
        tag = queries.create_tag('periods')
        queries.log_tag_usage(tag['id'], 10, 100, 'photo')

        for period in ('all', 'hour', 'day', 'week', 'two_weeks'):
            with self.subTest(period=period):
                response = self.client.get(f'/admin?period={period}&date_from=&date_to=')
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'data-period="{period}" aria-pressed="true"', response.text)
                fragment = self.client.get(f'/admin/tag-usage/fragment?period={period}')
                self.assertEqual(fragment.status_code, 200)
                self.assertIn(f'data-period="{period}" aria-pressed="true"', fragment.json()['html'])
                self.assertNotIn('<!doctype html>', fragment.json()['html'])

        today = date.today().isoformat()
        custom = self.client.get(f'/admin?period=custom&date_from={today}&date_to={today}')
        self.assertEqual(custom.status_code, 200)
        self.assertIn('data-period="custom" aria-pressed="true"', custom.text)
        self.assertIn('data-date-range', custom.text)
        custom_fragment = self.client.get(
            f'/admin/tag-usage/fragment?period=custom&date_from={today}&date_to={today}',
        )
        self.assertEqual(custom_fragment.status_code, 200)
        self.assertIn('data-usage-form', custom_fragment.json()['html'])
        self.assertEqual(self.client.get('/admin?period=custom').status_code, 400)
        self.assertEqual(self.client.get('/admin?period=unknown').status_code, 400)
        self.assertEqual(self.client.get('/admin/tag-usage/fragment?period=unknown').status_code, 400)
        self.assertEqual(
            self.client.get('/admin?period=custom&date_from=2026-02-02&date_to=2026-02-01').status_code,
            400,
        )

    def test_admin_edits_player_profile(self):
        csrf = self.admin_session()
        user = queries.ensure_user(100, 'player')
        queries.db(
            '''
            INSERT INTO games (code, name) VALUES
                ('genshin', 'Genshin Impact'), ('hsr', 'Honkai: Star Rail'), ('zzz', 'Zenless Zone Zero')
            ON CONFLICT (code) DO NOTHING
            '''
        ).close()

        listing = self.client.get('/admin/players')
        editor = self.client.get(f'/admin/players/{user["id"]}/edit')
        self.assertEqual(listing.status_code, 200)
        self.assertIn('player', listing.text)
        self.assertEqual(editor.status_code, 200)
        self.assertIn('Genshin Impact', editor.text)

        response = self.client.post(f'/admin/players/{user["id"]}/edit', data={
            'bio': 'Player biography', 'birthday': '05.02', 'games': ['genshin', 'zzz'],
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_user_card(user['id'])['bio'], 'Player biography')
        self.assertEqual(queries.get_birthday(100), {'day': 5, 'month': 2, 'year': None})
        self.assertEqual(queries.get_user_games(user['id']), {'genshin', 'zzz'})
        public_profile = self.client.get(f'/users/{user["id"]}')
        self.assertIn('Player biography', public_profile.text)
        self.assertIn('Genshin Impact', public_profile.text)
        self.assertIn('Zenless Zone Zero', public_profile.text)

        response = self.client.post(f'/admin/players/{user["id"]}/edit', data={
            'bio': 'Updated biography', 'birthday': '2000-02-29', 'games': ['hsr'],
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_birthday(100), {'day': 29, 'month': 2, 'year': 2000})
        self.assertEqual(queries.get_user_games(user['id']), {'hsr'})
        self.assertIn('2000-02-29', self.client.get(f'/admin/players/{user["id"]}/edit').text)

        response = self.client.post(f'/admin/players/{user["id"]}/edit', data={
            'bio': '', 'birthday': '', 'games': [], 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(queries.get_user_card(user['id'])['bio'])
        self.assertIsNone(queries.get_birthday(100))
        self.assertEqual(queries.get_user_games(user['id']), set())
        self.assertEqual(
            queries.db("SELECT COUNT(*) AS cnt FROM admin_audit_log WHERE entity_type = 'user'").one()['cnt'],
            3,
        )

    def test_player_titles_crud_and_character_profile_data_stay_separate(self):
        csrf = self.admin_session()
        user = queries.ensure_user(100, 'player')

        response = self.client.post(f'/admin/players/{user["id"]}/edit', data={
            'bio': 'Player biography', 'birthday': '05.02',
            'chat_position': 'Модератор', 'games': [], 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_user_by_id(user['id'])['chat_position'], 'Модератор')

        for title in ('Архивариус', 'Хранитель летописи'):
            response = self.client.post(f'/admin/players/{user["id"]}/titles', data={
                'name': title, 'csrf_token': csrf,
            }, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
        duplicate = self.client.post(f'/admin/players/{user["id"]}/titles', data={
            'name': 'архивариус', 'csrf_token': csrf,
        })
        self.assertEqual(duplicate.status_code, 400)
        titles = queries.get_user_titles(user['id'])
        self.assertEqual([title['name'] for title in titles], ['Архивариус', 'Хранитель летописи'])

        profile = self.client.get(f'/users/{user["id"]}')
        self.assertIn('Player biography', profile.text)
        self.assertIn('Архивариус', profile.text)
        self.assertIn('Хранитель летописи', profile.text)
        self.assertIn('Модератор', profile.text)
        self.assertIn('05.02', profile.text)
        self.assertEqual(self.client.get('/admin/roles').status_code, 404)
        self.assertIsNone(queries.db(
            "SELECT 1 AS present FROM pg_tables WHERE tablename = 'flavor_roles'",
        ).one())

        response = self.client.post(
            f'/admin/players/{user["id"]}/titles/{titles[0]["id"]}/delete',
            data={'csrf_token': csrf}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            [title['name'] for title in queries.get_user_titles(user['id'])],
            ['Хранитель летописи'],
        )

        character = queries.create_character_row(
            user['id'], 'Фокалорс', date(2001, 2, 3), 'character-photo',
            'Character history', True,
        )
        queries.db(
            "UPDATE character SET wiki_url = 'https://wiki.example/focalors' WHERE id = %s",
            (character['id'],),
        ).close()
        direct_tag = queries.create_tag('Фокалорс')
        alias_tag = queries.create_tag('Фурина')
        queries.db(
            'INSERT INTO tag_alias (tag_id, alias) VALUES (%s, %s)',
            (alias_tag['id'], 'Фокалорс'),
        ).close()

        profile_with_character = self.client.get(f'/users/{user["id"]}')
        self.assertIn(f'/media/characters/{character["id"]}', profile_with_character.text)
        self.assertIn('Основной', profile_with_character.text)
        character_page = self.client.get(f'/characters/{character["id"]}')
        self.assertIn('Character history', character_page.text)
        self.assertNotIn('Player biography', character_page.text)
        self.assertIn('https://wiki.example/focalors', character_page.text)
        self.assertIn(f'href="/media?tag={direct_tag["id"]}">Фокалорс</a>', character_page.text)
        self.assertIn(f'href="/media?tag={alias_tag["id"]}">Фурина</a>', character_page.text)

    def test_admin_player_validation_is_atomic(self):
        csrf = self.admin_session()
        user = queries.ensure_user(100, 'player')
        url = f'/admin/players/{user["id"]}/edit'

        invalid_responses = [
            self.client.post(url, data={'bio': 'x' * 601, 'birthday': '', 'csrf_token': csrf}),
            self.client.post(url, data={'bio': 'Bio', 'birthday': '31.02', 'csrf_token': csrf}),
            self.client.post(url, data={'bio': 'Bio', 'birthday': '3000-01-01', 'csrf_token': csrf}),
            self.client.post(url, data={
                'bio': 'Bio', 'birthday': '05.02', 'games': ['unknown'], 'csrf_token': csrf,
            }),
        ]

        self.assertEqual([response.status_code for response in invalid_responses], [400] * 4)
        self.assertIsNone(queries.get_user_card(user['id']))
        self.assertIsNone(queries.get_birthday(100))
        self.assertEqual(queries.get_user_games(user['id']), set())
        self.assertEqual(self.client.get('/admin/players/999/edit').status_code, 404)
        self.assertEqual(self.client.post(
            '/admin/players/999/edit', data={'bio': '', 'birthday': '', 'csrf_token': csrf},
        ).status_code, 404)

    def test_admin_creates_character_and_reassigns(self):
        csrf = self.admin_session()
        first = queries.ensure_user(100, 'first')
        second = queries.ensure_user(200, 'second')

        response = self.client.post('/admin/characters', data={
            'owner_user_id': first['id'], 'name': 'Hero', 'birth_date': '',
            'description': 'Description', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        character = queries.db("SELECT * FROM character WHERE name = 'Hero'").one()
        self.assertEqual(character['owner_user_id'], first['id'])
        self.assertTrue(character['is_primary'])

        response = self.client.post(f"/admin/characters/{character['id']}/assign", data={
            'owner_user_id': second['id'], 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_character_by_id(character['id'])['owner_user_id'], second['id'])
        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM admin_audit_log').one()['cnt'], 2)

    def test_admin_uploads_and_removes_character_photo(self):
        import tempfile
        from web.media import TelegramMediaStore

        csrf = self.admin_session()
        user = queries.ensure_user(100, 'player')
        character = queries.create_character_row(user['id'], 'Hero', None, None, 'Description', True)
        image = b'\x89PNG\r\n\x1a\nimage-content'

        with tempfile.TemporaryDirectory() as cache_dir:
            store = TelegramMediaStore(cache_dir, 'test-token')
            with (
                patch('web.routes.admin.get_media_store', return_value=store),
                patch('web.routes.public.get_media_store', return_value=store),
            ):
                response = self.client.post(f"/admin/characters/{character['id']}/edit", data={
                    'name': 'Hero', 'birth_date': '', 'description': 'Description',
                    'wiki_url': 'https://wiki.example/hero', 'csrf_token': csrf,
                }, files={'photo': ('hero.png', image, 'image/png')}, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                updated = queries.get_character_by_id(character['id'])
                self.assertTrue(updated['photo_file_id'].startswith('local:'))
                self.assertEqual(updated['wiki_url'], 'https://wiki.example/hero')
                photo_response = self.client.get(f"/media/characters/{character['id']}")
                self.assertEqual(photo_response.status_code, 200)
                self.assertEqual(photo_response.content, image)

                response = self.client.post(f"/admin/characters/{character['id']}/edit", data={
                    'name': 'Hero', 'birth_date': '', 'description': 'Description',
                    'wiki_url': '', 'remove_photo': 'true', 'csrf_token': csrf,
                }, follow_redirects=False)
                self.assertEqual(response.status_code, 303)
                self.assertIsNone(queries.get_character_by_id(character['id'])['photo_file_id'])
                self.assertEqual(self.client.get(f"/media/characters/{character['id']}").status_code, 404)

    def test_admin_manages_positions_and_character_assignment(self):
        csrf = self.admin_session()
        user = queries.ensure_user(100, 'player')
        response = self.client.post('/admin/positions', data={
            'name': 'Leader', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        position_id = queries.get_position_by_name('Leader')['id']
        first = queries.create_character_row(user['id'], 'First', None, None, 'Old', True)
        second = queries.create_character_row(user['id'], 'Second', None, None, 'Other', False)

        response = self.client.post(f'/admin/positions/{position_id}/edit', data={
            'name': 'Leader updated', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNotNone(queries.get_position_by_name('Leader updated'))
        self.assertIn('Leader updated', self.client.get('/admin/characters').text)

        response = self.client.post(f'/admin/characters/{first["id"]}/edit', data={
            'name': 'Renamed', 'birth_date': '2001-02-03', 'position_id': str(position_id),
            'description': 'Updated', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        updated_character = queries.get_character_by_id(first['id'])
        self.assertEqual(updated_character['name'], 'Renamed')
        self.assertEqual(updated_character['position_id'], position_id)

        response = self.client.post(f'/admin/characters/{second["id"]}/edit', data={
            'name': 'Second', 'birth_date': '', 'position_id': str(position_id),
            'description': 'Other', 'csrf_token': csrf,
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn('Должность уже занята', response.text)
        self.assertIsNone(queries.get_character_by_id(second['id'])['position_id'])

        response = self.client.post(f'/admin/characters/{first["id"]}/delete', data={
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(queries.get_character_by_id(first['id']))
        self.assertTrue(queries.get_character_by_id(second['id'])['is_primary'])

        response = self.client.post(f'/admin/positions/{position_id}/delete', data={
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(queries.get_position_by_name('Leader updated'))

    def test_admin_manages_tag_aliases_and_character_links(self):
        csrf = self.admin_session()
        user = queries.ensure_user(100, 'player')
        character = queries.create_character_row(user['id'], 'Фокалорс', None, None, None, True)
        tag = queries.create_tag('Фурина')

        listing = self.client.get('/admin/tags')
        response = self.client.post('/admin/tags/aliases', data={
            'tag_id': tag['id'], 'alias': 'фока', 'csrf_token': csrf,
        }, follow_redirects=False)

        self.assertEqual(listing.status_code, 200)
        self.assertIn('Теги и алиасы', listing.text)
        self.assertEqual(response.status_code, 303)
        alias = queries.db("SELECT * FROM tag_alias WHERE alias = 'фока'").one()
        self.assertEqual(alias['tag_id'], tag['id'])

        duplicate = self.client.post('/admin/tags/aliases', data={
            'tag_id': tag['id'], 'alias': 'фока', 'csrf_token': csrf,
        })
        self.assertEqual(duplicate.status_code, 400)
        self.assertIn('уже привязан', duplicate.text)

        response = self.client.post('/admin/tags/characters', data={
            'character_id': character['id'], 'tag_id': tag['id'], 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            {row['alias'] for row in queries.get_all_tag_aliases()}, {'фока', 'Фокалорс'},
        )
        from web.queries import list_admin_character_tag_links
        links = list_admin_character_tag_links()
        self.assertEqual(links[0]['tag_names'], 'Фурина')
        self.assertEqual(queries.get_character_by_id(character['id'])['owner_user_id'], user['id'])

        page = self.client.get('/admin/tags')
        self.assertIn('фока', page.text)
        self.assertIn('Фокалорс', page.text)
        self.assertNotIn('#фока', page.text)
        self.assertIn('data-local-search', page.text)
        self.assertIn('data-tag-search', page.text)
        filtered = self.client.get('/admin/tags?q=фока')
        self.assertIn('Фурина', filtered.text)
        self.assertIn('Теги не найдены', self.client.get('/admin/tags?q=ока').text)
        response = self.client.post(f"/admin/tags/aliases/{alias['id']}/delete", data={
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            {row['alias'] for row in queries.get_all_tag_aliases()}, {'Фокалорс'},
        )

        queen = queries.create_character_row(user['id'], 'Царица', None, None, None, False)
        queries.create_tag('Царица')
        self.assertEqual(len(list_admin_character_tag_links('Фок')), 1)
        self.assertEqual(list_admin_character_tag_links('ока'), [])
        self.assertEqual(list_admin_character_tag_links('Цар')[0]['name'], 'Царица')
        character_page = self.client.get('/admin/tags?character_q=Фок')
        self.assertIn('id="character-links" open', character_page.text)
        conflict = self.client.post('/admin/tags/characters', data={
            'character_id': queen['id'], 'tag_id': tag['id'], 'csrf_token': csrf,
        })
        self.assertEqual(conflict.status_code, 400)
        self.assertIn('основным тегом «Царица»', conflict.text)
        self.assertIn('у персонажа «Царица»', conflict.text)

        detail = self.client.get(f"/admin/tags/{tag['id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn('Фокалорс', detail.text)
        character_alias = queries.db("SELECT * FROM tag_alias WHERE alias = 'Фокалорс'").one()
        response = self.client.post(
            f"/admin/tags/{tag['id']}/aliases/{character_alias['id']}/delete",
            data={'csrf_token': csrf}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_all_tag_aliases(), [])

        invalid_status = self.client.post(f"/admin/tags/{tag['id']}/status", data={
            'status': 'UNKNOWN', 'csrf_token': csrf,
        })
        self.assertEqual(invalid_status.status_code, 400)
        response = self.client.post(f"/admin/tags/{tag['id']}/status", data={
            'status': 'BLOCKED', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_tag_by_id(tag['id'])['status'], 'BLOCKED')
        self.assertIn('Фурина', self.client.get('/admin/tags?status=BLOCKED').text)
        self.assertNotIn('Фурина', self.client.get('/admin/tags?status=ACTIVE').text)

        response = self.client.post(f"/admin/tags/{tag['id']}/delete", data={
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(queries.get_tag_by_id(tag['id']))
        self.assertEqual(self.client.get(f"/admin/tags/{tag['id']}").status_code, 404)
        self.assertEqual(
            queries.db("SELECT COUNT(*) AS cnt FROM admin_audit_log WHERE entity_type = 'tag_alias'").one()['cnt'],
            4,
        )

    def test_admin_manages_affiliations_and_multiple_character_links(self):
        csrf = self.admin_session()
        user = queries.ensure_user(100, 'player')
        character = queries.create_character_row(user['id'], 'Фокалорс', None, None, None, True)

        root = self.client.post('/admin/affiliations', data={
            'name': 'Фатуи', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(root.status_code, 303)
        root_row = queries.db("SELECT * FROM affiliations WHERE name = 'Фатуи'").one()
        child = self.client.post('/admin/affiliations', data={
            'name': 'Предвестник', 'parent_id': root_row['id'], 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(child.status_code, 303)
        child_row = queries.db("SELECT * FROM affiliations WHERE name = 'Предвестник'").one()

        self.assertIn('Фатуи', self.client.get('/admin/affiliations?q=Фа').text)
        self.assertIn('Принадлежности не найдены', self.client.get('/admin/affiliations?q=ату').text)
        duplicate = self.client.post('/admin/affiliations', data={
            'name': 'Фатуи', 'csrf_token': csrf,
        })
        self.assertEqual(duplicate.status_code, 400)

        for affiliation_id in (root_row['id'], child_row['id']):
            response = self.client.post('/admin/affiliations/characters', data={
                'character_id': character['id'], 'affiliation_id': affiliation_id, 'csrf_token': csrf,
            }, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
        public_character = self.client.get(f"/characters/{character['id']}")
        self.assertIn('Фатуи', public_character.text)
        self.assertIn('Предвестник', public_character.text)
        duplicate_link = self.client.post('/admin/affiliations/characters', data={
            'character_id': character['id'], 'affiliation_id': root_row['id'], 'csrf_token': csrf,
        })
        self.assertEqual(duplicate_link.status_code, 400)

        response = self.client.post(f"/admin/affiliations/{child_row['id']}/edit", data={
            'name': 'Предвестники', 'parent_id': root_row['id'], 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        cycle = self.client.post(f"/admin/affiliations/{root_row['id']}/edit", data={
            'name': 'Фатуи', 'parent_id': child_row['id'], 'csrf_token': csrf,
        })
        self.assertEqual(cycle.status_code, 400)
        self.assertIn('дочернюю', cycle.text)

        self.assertIn('Фокалорс', self.client.get('/admin/affiliations?character_q=Фок').text)
        self.assertIn('Персонажи не найдены', self.client.get('/admin/affiliations?character_q=ока').text)
        response = self.client.post(
            f"/admin/affiliations/characters/{character['id']}/{root_row['id']}/delete",
            data={'csrf_token': csrf}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        remaining = queries.db('SELECT * FROM character_affiliation').all()
        self.assertEqual([row['affiliation_id'] for row in remaining], [child_row['id']])

        response = self.client.post(f"/admin/affiliations/{child_row['id']}/delete", data={
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM character_affiliation').one()['cnt'], 0)
        response = self.client.post(f"/admin/affiliations/{root_row['id']}/delete", data={
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        from web.queries import get_admin_affiliation
        self.assertIsNone(get_admin_affiliation(root_row['id']))
        self.assertGreaterEqual(
            queries.db("SELECT COUNT(*) AS cnt FROM admin_audit_log WHERE entity_type LIKE '%%affiliation%%'").one()['cnt'],
            8,
        )

    def test_media_moderation_keeps_analytics(self):
        csrf = self.admin_session()
        tag = queries.create_tag('nature')
        queries.log_tag_usage(
            tag['id'], 10, 100, 'photo', chat_id=200,
            media_file_id='photo-file', media_file_unique_id='photo-unique', caption='Visible photo',
        )
        second_tag = queries.create_tag('landscape')
        queries.log_tag_usage(
            second_tag['id'], 10, 100, 'photo', chat_id=200,
            media_file_id='photo-file', media_file_unique_id='photo-unique', caption='Visible photo',
        )
        usage = queries.db('SELECT * FROM tag_usage ORDER BY id LIMIT 1').one()

        response = self.client.post(f"/admin/media/{usage['id']}/visibility", data={
            'is_public': 'false', 'csrf_token': csrf,
        }, follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertNotIn('Visible photo', self.client.get('/media').text)
        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM tag_usage WHERE is_public').one()['cnt'], 0)
        from web.queries import get_daily_analytics
        self.assertEqual(get_daily_analytics(__import__('datetime').date.today())['total'], 2)

    def test_users_search_and_infinite_scroll(self):
        for index in range(14):
            queries.ensure_user(1000 + index, f'player-{index:02}')
        queries.ensure_user(2000, 'needle')

        first_page = self.client.get('/users')
        second_page = self.client.get('/users/fragment?page=2')
        search = self.client.get('/users?q=needle')

        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(first_page.text.count('class="profile-card"'), 12)
        self.assertEqual(second_page.status_code, 200)
        self.assertEqual(second_page.json()['html'].count('class="profile-card"'), 3)
        self.assertIsNone(second_page.json()['next_url'])
        self.assertEqual(search.text.count('class="profile-card"'), 1)
        self.assertIn('needle', search.text)
        self.assertNotIn('player-00', search.text)

    def test_user_avatar_is_cached(self):
        user = queries.ensure_user(100, 'player')
        store = SimpleNamespace(
            get_profile_photo_file_id=AsyncMock(return_value='avatar-file'),
            get_response=AsyncMock(return_value=Response(content=b'avatar', media_type='image/jpeg')),
        )

        with patch('web.routes.public.get_media_store', return_value=store):
            first = self.client.get(f'/media/users/{user["id"]}/avatar')
            second = self.client.get(f'/media/users/{user["id"]}/avatar')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(store.get_profile_photo_file_id.await_count, 1)
        self.assertEqual(store.get_response.await_count, 2)
        self.assertEqual(queries.get_user_by_id(user['id'])['avatar_file_id'], 'avatar-file')

    def test_telegram_metadata_is_persisted(self):
        from handlers.tags.tagging import _log_tag_message_usage

        tag = queries.create_tag('photos')
        photo = SimpleNamespace(file_id='file-id', file_unique_id='unique-id')
        update = SimpleNamespace(
            effective_chat=SimpleNamespace(id=200),
            effective_message=SimpleNamespace(
                message_thread_id=30, message_id=40, caption='Caption', text=None,
                photo=[photo], video=None,
            ),
        )

        _log_tag_message_usage(update, tag['id'], 100, 'photo')

        usage = queries.db('SELECT * FROM tag_usage').one()
        self.assertEqual(usage['chat_id'], 200)
        self.assertEqual(usage['media_file_id'], 'file-id')
        self.assertEqual(usage['media_file_unique_id'], 'unique-id')
        self.assertEqual(usage['caption'], 'Caption')
