import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


class NewsMarkdownTests(unittest.TestCase):
    def test_markdown_is_formatted_and_raw_html_is_escaped(self):
        from services.news_markdown import render_news_markdown, telegram_news_text

        source = (
            '## Заголовок\n**Жирный** *курсив* __подчёркивание__ ~~зачёркивание~~ '
            '[ссылка](https://example.com) <script>alert(1)</script>\n- пункт'
        )
        rendered = render_news_markdown(source)
        self.assertIn('<h2>Заголовок</h2>', rendered)
        self.assertIn('<b>Жирный</b>', rendered)
        self.assertIn('<i>курсив</i>', rendered)
        self.assertIn('<u>подчёркивание</u>', rendered)
        self.assertIn('<s>зачёркивание</s>', rendered)
        self.assertIn('<a href="https://example.com">ссылка</a>', rendered)
        self.assertIn('<ul><li>пункт</li></ul>', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)

        telegram = telegram_news_text({'title': 'Новость', 'content': source})
        self.assertTrue(telegram.startswith('<b>Новость</b>'))
        self.assertIn('<b>Заголовок</b>', telegram)
        self.assertIn('• пункт', telegram)


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class AccountNewsIntegrationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        from web.app import create_app
        from web.auth import SESSION_COOKIE, create_admin_session

        queries.db("INSERT INTO games (code, name) VALUES ('genshin', 'Genshin Impact')").close()
        self.user = queries.ensure_user(100, 'player')
        queries.add_admin(100)
        token, self.csrf = create_admin_session(100)
        self.client = TestClient(create_app())
        self.client.cookies.set(SESSION_COOKIE, token)

    def tearDown(self):
        self.client.close()

    def test_account_shows_rewards_tierlists_and_returns_after_login(self):
        from database.tierlists import create_tier_list
        from database.wishes import get_or_create_current_wish_event
        from database.wish_rewards import record_wish_activity

        event = get_or_create_current_wish_event()
        record_wish_activity('daily_message', self.user['id'], 'test', 'message-1', event['id'])
        create_tier_list(self.user['id'], 'Мой кабинетный список', ['genshin'])

        response = self.client.get('/account')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('Личный кабинет', response.text)
        self.assertIn('Мой кабинетный список', response.text)
        self.assertIn('Первое сообщение дня', response.text)
        self.assertIn('Уровень 1/3', response.text)
        self.assertIn('+1', response.text)
        own_profile = self.client.get(f'/users/{self.user["id"]}')
        self.assertEqual(own_profile.status_code, 200)
        self.assertIn('Личный кабинет', own_profile.text)
        self.assertIn('Уровни достижений', own_profile.text)
        other = queries.ensure_user(200, 'other')
        other_profile = self.client.get(f'/users/{other["id"]}')
        self.assertEqual(other_profile.status_code, 200)
        self.assertNotIn('account-stats', other_profile.text)
        self.assertNotIn('Последние награды', other_profile.text)
        self.assertIn('data-nav-group', other_profile.text)
        self.assertIn('Сообщество', other_profile.text)

        response = self.client.post(
            '/account/logout', data={'csrf_token': self.csrf}, follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/')
        self.client.cookies.clear()
        login_required = self.client.get('/account', follow_redirects=False)
        self.assertEqual(login_required.status_code, 303)
        self.assertEqual(
            login_required.headers['location'], '/tierlists/login?next=/account',
        )
        with patch('web.routes.tierlists.verify_telegram_login', return_value=True):
            login = self.client.get(
                '/tierlists/login/telegram',
                params={'id': 100, 'next': '/account'},
                follow_redirects=False,
            )
        self.assertEqual(login.status_code, 303)
        self.assertEqual(login.headers['location'], '/account')
        self.assertEqual(self.client.get('/account').status_code, 200)

    def test_profile_places_role_under_name_and_subscriptions_after_characters(self):
        queries.db(
            "UPDATE users SET chat_position = 'Хранитель архива' WHERE id = %s",
            (self.user['id'],),
        ).close()
        queries.create_character_row(
            self.user['id'], 'Фурина', None, None, 'Описание', True,
        )
        tag = queries.create_tag('adventure')
        queries.subscribe_tag(self.user['tg_id'], tag['id'])

        response = self.client.get('/account')

        self.assertEqual(response.status_code, 200, response.text)
        nickname = response.text.index('<h1>player</h1>')
        position = response.text.index('account-profile-position')
        facts = response.text.index('account-profile-facts')
        self.assertLess(nickname, position)
        self.assertLess(position, facts)
        self.assertIn('Хранитель архива', response.text)
        self.assertNotIn('<dt>Должность в чате</dt>', response.text)
        self.assertLess(
            response.text.index('id="characters"'),
            response.text.index('id="subscriptions"'),
        )
        self.assertIn('adventure', response.text)

    def test_news_admin_public_home_and_telegram_action(self):
        response = self.client.post('/admin/news/new', data={
            'title': 'Черновик обновления', 'summary': 'Кратко об изменениях',
            'content': 'Полный текст новости', 'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        from database.news import get_admin_news

        post = get_admin_news(1)
        self.assertFalse(post['is_published'])
        self.assertNotIn('Черновик обновления', self.client.get('/news').text)
        self.assertEqual(self.client.get('/news/1').status_code, 404)

        image = Path('web/static/tierlists/characters/furina.webp').read_bytes()
        with patch(
            'web.routes.news_admin.send_news_to_telegram',
            new=AsyncMock(return_value={'telegram_message_id': 42}),
        ) as send:
            response = self.client.post(
                '/admin/news/1/edit',
                data={
                    'title': 'Большое обновление', 'summary': 'ЛК и новости уже здесь',
                    'content': '## Возможности\n**Жирный** текст\n- пункт',
                    'tags': 'обновление, лк', 'cover_alt': 'Обложка обновления',
                    'is_published': 'true', 'send_telegram': 'true', 'csrf_token': self.csrf,
                },
                files={'photo': ('cover.webp', image, 'image/webp')},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 303, response.text)
        send.assert_awaited_once()
        post = get_admin_news(1)
        self.assertEqual(post['tags'], ['обновление', 'лк'])
        self.assertTrue(post['cover_image'].startswith('/media/news/'))
        self.assertIn('Большое обновление', self.client.get('/news').text)
        self.assertIn('#обновление', self.client.get('/news').text)
        self.assertIn('player', self.client.get('/news').text)
        detail = self.client.get('/news/1')
        self.assertEqual(detail.status_code, 200)
        self.assertIn('ЛК и новости уже здесь', detail.text)
        self.assertIn('news-detail-content', detail.text)
        self.assertIn('<h2>Возможности</h2>', detail.text)
        self.assertIn('<b>Жирный</b>', detail.text)
        self.assertIn(post['cover_image'], detail.text)
        self.assertIn('Большое обновление', self.client.get('/').text)
        self.assertEqual(self.client.get('/news?tag=лк').status_code, 200)
        self.assertIn('Большое обновление', self.client.get('/news?tag=лк').text)
        self.assertNotIn('Большое обновление', self.client.get('/news?tag=другой').text)

        response = self.client.post('/admin/news/1/edit', data={
            'title': 'Большое обновление', 'summary': 'ЛК и новости уже здесь',
            'content': 'Текст', 'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.client.get('/news/1').status_code, 404)
        invalid = self.client.post('/admin/news/new', data={
            'title': '', 'summary': 'Описание', 'content': 'Текст', 'csrf_token': self.csrf,
        })
        self.assertEqual(invalid.status_code, 400)
        deleted = self.client.post(
            '/admin/news/1/delete', data={'csrf_token': self.csrf}, follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        self.assertEqual(self.client.get('/news/1').status_code, 404)
        self.assertEqual(self.client.get(post['cover_image']).status_code, 404)

    async def test_telegram_news_delivery_marker_and_failure(self):
        from database.news import create_news, get_admin_news
        from services.news_notifications import send_news_to_telegram

        queries.upsert_chat(-100500, 'Основной чат')
        post = create_news(100, 'Новость', 'Краткое описание', 'Текст', True)
        response = MagicMock()
        response.json.return_value = {'ok': True, 'result': {'message_id': 42}}
        http_client = MagicMock()
        http_client.__aenter__ = AsyncMock(return_value=http_client)
        http_client.__aexit__ = AsyncMock(return_value=False)
        http_client.post = AsyncMock(return_value=response)

        with patch(
            'services.news_notifications.httpx.AsyncClient', return_value=http_client,
        ):
            sent = await send_news_to_telegram(post)
            self.assertEqual(sent['telegram_message_id'], 42)
            self.assertIsNone(await send_news_to_telegram(sent))
            request = http_client.post.await_args.kwargs['json']
            self.assertEqual(request['chat_id'], -100500)
            self.assertIn('<b>Новость</b>', request['text'])
            self.assertIn('Текст', request['text'])
            self.assertEqual(request['parse_mode'], 'HTML')
            self.assertEqual(
                request['reply_markup']['inline_keyboard'][0][0]['url'],
                'http://testserver/news/1',
            )

            failed_post = create_news(100, 'Ошибка', 'Не отправлено', 'Текст', True)
            response.json.return_value = {'ok': False}
            self.assertIsNone(await send_news_to_telegram(failed_post))

        self.assertIsNotNone(get_admin_news(post['id'])['telegram_sent_at'])
        self.assertIsNone(get_admin_news(failed_post['id'])['telegram_sent_at'])

    async def test_telegram_news_with_cover_uses_photo(self):
        from database.news import create_news
        from services.news_notifications import send_news_to_telegram

        queries.upsert_chat(-100500, 'Основной чат')
        filename = 'a' * 32 + '.webp'
        path = Path('data/test-media/uploads') / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        image = Path('web/static/tierlists/characters/furina.webp').read_bytes()
        path.write_bytes(image)
        post = create_news(
            100, 'С обложкой', 'Кратко', '**Важный** текст', True,
            cover_image=f'/media/news/{filename}',
        )
        response = MagicMock()
        response.json.return_value = {'ok': True, 'result': {'message_id': 43}}
        http_client = MagicMock()
        http_client.__aenter__ = AsyncMock(return_value=http_client)
        http_client.__aexit__ = AsyncMock(return_value=False)
        http_client.post = AsyncMock(return_value=response)
        try:
            with patch(
                'services.news_notifications.httpx.AsyncClient', return_value=http_client,
            ):
                sent = await send_news_to_telegram(post)
            self.assertEqual(sent['telegram_message_id'], 43)
            call = http_client.post.await_args
            self.assertTrue(call.args[0].endswith('/sendPhoto'))
            self.assertEqual(call.kwargs['data']['parse_mode'], 'HTML')
            self.assertIn('<b>Важный</b>', call.kwargs['data']['caption'])
            self.assertEqual(call.kwargs['files']['photo'][1], image)
        finally:
            path.unlink(missing_ok=True)
