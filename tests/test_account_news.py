import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


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

        with patch(
            'web.routes.news_admin.send_news_to_telegram',
            new=AsyncMock(return_value={'telegram_message_id': 42}),
        ) as send:
            response = self.client.post('/admin/news/1/edit', data={
                'title': 'Большое обновление', 'summary': 'ЛК и новости уже здесь',
                'content': 'Первая строка\nВторая строка', 'is_published': 'true',
                'send_telegram': 'true', 'csrf_token': self.csrf,
            }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        send.assert_awaited_once()
        self.assertIn('Большое обновление', self.client.get('/news').text)
        detail = self.client.get('/news/1')
        self.assertEqual(detail.status_code, 200)
        self.assertIn('ЛК и новости уже здесь', detail.text)
        self.assertIn('news-detail-content', detail.text)
        self.assertIn('Большое обновление', self.client.get('/').text)

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
            self.assertIn('Новость\n\nКраткое описание', request['text'])
            self.assertEqual(
                request['reply_markup']['inline_keyboard'][0][0]['url'],
                'http://testserver/news/1',
            )

            failed_post = create_news(100, 'Ошибка', 'Не отправлено', 'Текст', True)
            response.json.return_value = {'ok': False}
            self.assertIsNone(await send_news_to_telegram(failed_post))

        self.assertIsNotNone(get_admin_news(post['id'])['telegram_sent_at'])
        self.assertIsNone(get_admin_news(failed_post['id'])['telegram_sent_at'])
