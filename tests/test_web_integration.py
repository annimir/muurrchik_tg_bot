import unittest
from types import SimpleNamespace

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
        queries.log_tag_usage(
            tag['id'], 10, 100, 'photo', chat_id=200,
            media_file_id='photo-file', media_file_unique_id='photo-unique', caption='Forest photo',
        )
        queries.log_tag_usage(
            tag['id'], 11, 100, 'video_link', chat_id=200,
            media_url='https://youtu.be/video-id', caption='Video link',
        )

        home = self.client.get('/')
        catalog = self.client.get('/media?kind=photo')
        characters = self.client.get('/characters')

        self.assertEqual(home.status_code, 200)
        self.assertIn('Летопись', home.text)
        self.assertIn('Forest photo', catalog.text)
        self.assertNotIn('Video link', catalog.text)
        self.assertIn('Hero', characters.text)

    def test_admin_requires_telegram_session_and_csrf(self):
        response = self.client.get('/admin', follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        token, _ = self.admin_session()
        response = self.client.post('/admin/roles', data={'name': 'Role', 'csrf_token': token + 'bad'})
        self.assertEqual(response.status_code, 403)

    def test_admin_creates_role_character_and_reassigns(self):
        csrf = self.admin_session()
        first = queries.ensure_user(100, 'first')
        second = queries.ensure_user(200, 'second')

        response = self.client.post('/admin/roles', data={
            'name': 'Guard', 'description': 'Description', 'wiki_url': '', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_flavor_role_by_name('Guard')['name'], 'Guard')

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
        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM admin_audit_log').one()['cnt'], 3)

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
