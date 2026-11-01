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
        queries.log_tag_usage(
            tag['id'], 10, 100, 'photo', chat_id=200,
            media_file_id='photo-file', media_file_unique_id='photo-unique', caption='Forest photo',
        )
        second_tag = queries.create_tag('forest')
        queries.log_tag_usage(
            second_tag['id'], 10, 100, 'photo', chat_id=200,
            media_file_id='photo-file', media_file_unique_id='photo-unique', caption='Forest photo',
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
        empty_filters = self.client.get('/media?tag=&kind=&date_from=&date_to=')
        today = date.today().isoformat()
        dated = self.client.get(f'/media?date_from={today}&date_to={today}')
        outside = self.client.get('/media?date_to=2000-01-01')
        characters = self.client.get('/characters')

        self.assertEqual(home.status_code, 200)
        self.assertIn('Летопись', home.text)
        self.assertIn('muted playsinline', home.text)
        self.assertIn('data-media-open=', home.text)
        self.assertIn('Forest photo', catalog.text)
        self.assertIn('#adventure', catalog.text)
        self.assertIn('#forest', catalog.text)
        self.assertIn('Автор:', catalog.text)
        self.assertIn('player', catalog.text)
        self.assertNotIn('Video link', catalog.text)
        self.assertEqual(empty_filters.status_code, 200)
        self.assertIn('Forest photo', dated.text)
        self.assertIn('Video link', dated.text)
        self.assertIn('Muted video', dated.text)
        self.assertNotIn('Forest photo', outside.text)
        self.assertIn('Hero', characters.text)

    def test_admin_requires_telegram_session_and_csrf(self):
        response = self.client.get('/admin', follow_redirects=False)
        self.assertEqual(response.status_code, 303)

        csrf = self.admin_session()
        response = self.client.post('/admin/roles', data={'name': 'Role', 'csrf_token': csrf + 'bad'})
        self.assertEqual(response.status_code, 403)

    def test_admin_dashboard_renders(self):
        self.admin_session()
        tag = queries.create_tag('daily')
        queries.log_tag_usage(tag['id'], 10, 100, 'photo')

        response = self.client.get('/admin')

        self.assertEqual(response.status_code, 200)
        self.assertIn('Статистика сообщества', response.text)
        self.assertIn('Использование тегов за 14 дней', response.text)
        self.assertIn('#daily', response.text)

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

    def test_admin_edits_and_deletes_characters_and_roles(self):
        csrf = self.admin_session()
        user = queries.ensure_user(100, 'player')
        role_id = queries.add_flavor_role('Old role')
        queries.set_user_flavor_role(user['id'], role_id)
        first = queries.create_character_row(user['id'], 'First', None, None, 'Old', True)
        second = queries.create_character_row(user['id'], 'Second', None, None, 'Other', False)

        response = self.client.post(f'/admin/roles/{role_id}/edit', data={
            'name': 'New role', 'description': 'Updated', 'wiki_url': '', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_flavor_role_by_id(role_id)['name'], 'New role')

        response = self.client.post(f'/admin/characters/{first["id"]}/edit', data={
            'name': 'Renamed', 'birth_date': '2001-02-03',
            'description': 'Updated', 'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(queries.get_character_by_id(first['id'])['name'], 'Renamed')

        response = self.client.post(f'/admin/characters/{first["id"]}/delete', data={
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(queries.get_character_by_id(first['id']))
        self.assertTrue(queries.get_character_by_id(second['id'])['is_primary'])

        response = self.client.post(f'/admin/roles/{role_id}/delete', data={
            'csrf_token': csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertIsNone(queries.get_flavor_role_by_id(role_id))
        self.assertIsNone(queries.get_user_by_id(user['id'])['flavor_role_id'])

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
