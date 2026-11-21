import unittest
from datetime import date

from fastapi.testclient import TestClient

from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class CalendarIntegrationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        from web.app import create_app
        from web.auth import SESSION_COOKIE, create_admin_session

        queries.db(
            "INSERT INTO games (code, name) VALUES "
            "('genshin', 'Genshin Impact'), ('hsr', 'Honkai: Star Rail')"
        ).close()
        self.user = queries.ensure_user(100, 'player')
        queries.add_admin(100)
        token, self.csrf = create_admin_session(100)
        self.client = TestClient(create_app())
        self.client.cookies.set(SESSION_COOKIE, token)

    def tearDown(self):
        self.client.close()

    def _create_event(self, title='Витая бездна', game='genshin', event_type='event'):
        return self.client.post('/admin/calendar', data={
            'title': title, 'description': 'Описание события', 'game_code': game,
            'event_type': event_type, 'start_date': '2026-11-10', 'end_date': '2026-11-20',
            'url': 'https://example.com/event', 'csrf_token': self.csrf,
        }, follow_redirects=False)

    def test_admin_crud_public_calendar_and_filters(self):
        queries.set_birthday(100, 'player', 15, 11)
        queries.create_character_row(
            self.user['id'], 'Фурина', date(2000, 11, 16), None, 'Описание', True,
        )
        response = self._create_event()
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(self._create_event('Баннер новой версии', 'hsr', 'banner').status_code, 303)

        calendar = self.client.get('/calendar?year=2026&month=11')
        self.assertEqual(calendar.status_code, 200, calendar.text)
        for text in ('Витая бездна', 'Баннер новой версии', 'player', 'Фурина', 'Ноябрь'):
            self.assertIn(text, calendar.text)
        self.assertIn('href="/calendar"', self.client.get('/').text)

        genshin = self.client.get('/calendar?year=2026&month=11&game=genshin')
        self.assertIn('Витая бездна', genshin.text)
        self.assertNotIn('Баннер новой версии', genshin.text)
        self.assertIn('player', genshin.text)
        self.assertIn('Фурина', genshin.text)
        banners = self.client.get('/calendar?year=2026&month=11&type=banner')
        self.assertNotIn('Витая бездна', banners.text)
        self.assertIn('Баннер новой версии', banners.text)
        self.assertNotIn('Фурина', banners.text)
        players = self.client.get('/calendar?year=2026&month=11&type=player_birthday')
        self.assertIn('player', players.text)
        self.assertNotIn('Фурина', players.text)
        self.assertNotIn('Витая бездна', players.text)

        switched_month = self.client.get('/calendar?month_value=2026-12')
        self.assertEqual(switched_month.status_code, 200)
        self.assertIn('Декабрь', switched_month.text)
        self.assertNotIn('Витая бездна', switched_month.text)
        self.assertEqual(self.client.get('/calendar?year=2026&month=13').status_code, 400)
        self.assertEqual(self.client.get('/calendar?year=2026&month=0').status_code, 400)
        self.assertEqual(self.client.get('/calendar?month_value=invalid').status_code, 400)
        self.assertEqual(self.client.get('/calendar?game=unknown').status_code, 400)

        invalid = self.client.post('/admin/calendar/1/edit', data={
            'title': 'Неверный период', 'game_code': 'genshin', 'event_type': 'event',
            'start_date': '2026-11-21', 'end_date': '2026-11-20',
            'csrf_token': self.csrf,
        })
        self.assertEqual(invalid.status_code, 400)
        self.assertIn('Дата окончания', invalid.text)
        updated = self.client.post('/admin/calendar/1/edit', data={
            'title': 'Обновлённый ивент', 'description': '', 'game_code': 'genshin',
            'event_type': 'event', 'start_date': '2026-11-11', 'end_date': '2026-11-21',
            'url': '', 'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(updated.status_code, 303, updated.text)
        self.assertIn('Обновлённый ивент', self.client.get('/admin/calendar').text)
        deleted = self.client.post(
            '/admin/calendar/1/delete', data={'csrf_token': self.csrf}, follow_redirects=False,
        )
        self.assertEqual(deleted.status_code, 303)
        self.assertNotIn('Обновлённый ивент', self.client.get('/admin/calendar').text)

    def test_leap_birthdays_repeat_and_left_players_are_hidden(self):
        queries.set_birthday(100, 'player', 29, 2)
        queries.create_character_row(
            self.user['id'], 'Фурина', date(2000, 2, 29), None, None, True,
        )

        leap = self.client.get('/calendar?year=2028&month=2')
        regular = self.client.get('/calendar?year=2027&month=2')
        self.assertIn('player', leap.text)
        self.assertIn('Фурина', leap.text)
        self.assertIn('datetime="2028-02-29"', leap.text)
        self.assertIn('player', regular.text)
        self.assertIn('Фурина', regular.text)
        self.assertIn('datetime="2027-02-28"', regular.text)
        self.assertIn('29.02', regular.text)

        queries.db('UPDATE users SET left_at = now() WHERE id = %s', (self.user['id'],)).close()
        hidden = self.client.get('/calendar?year=2028&month=2')
        self.assertNotIn('agenda-player_birthday-', hidden.text)
        self.assertNotIn('agenda-character_birthday-', hidden.text)

    def test_multiday_event_crosses_month_and_input_is_validated(self):
        from database.calendar import create_calendar_event

        create_calendar_event(
            100, 'genshin', 'Переходящий ивент', '', 'event',
            date(2026, 1, 30), date(2026, 2, 2),
        )
        february = self.client.get('/calendar?year=2026&month=2')
        self.assertEqual(february.status_code, 200, february.text)
        self.assertIn('Переходящий ивент', february.text)
        self.assertEqual(february.text.count('class="calendar-event calendar-event-event"'), 2)
        self.assertIn('30.01–02.02.2026', february.text)

        for data in (
            {
                'title': 'Неверная ссылка', 'game_code': 'genshin', 'event_type': 'event',
                'start_date': '2026-11-01', 'end_date': '2026-11-02', 'url': 'javascript:alert(1)',
            },
            {
                'title': 'Неверный тип', 'game_code': 'genshin', 'event_type': 'other',
                'start_date': '2026-11-01', 'end_date': '2026-11-02',
            },
            {
                'title': 'Нет игры', 'game_code': 'unknown', 'event_type': 'event',
                'start_date': '2026-11-01', 'end_date': '2026-11-02',
            },
        ):
            response = self.client.post(
                '/admin/calendar', data={**data, 'csrf_token': self.csrf},
            )
            self.assertEqual(response.status_code, 400)

        self.client.cookies.clear()
        anonymous = self.client.get('/admin/calendar', follow_redirects=False)
        self.assertEqual(anonymous.status_code, 303)
