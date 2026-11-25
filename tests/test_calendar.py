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
        self.assertIn('--game-color: #d8bc72', calendar.text)
        self.assertIn('--game-color: #a89be8', calendar.text)
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

    def test_week_timeline_groups_categories_and_loads_fragments(self):
        from database.calendar import create_calendar_event
        from web.calendar_timeline import build_calendar_timeline

        queries.db("INSERT INTO games (code, name) VALUES ('zzz', 'Zenless Zone Zero')").close()
        queries.set_birthday(100, 'player', 15, 11)
        queries.create_character_row(
            self.user['id'], 'Фурина', date(2000, 11, 16), None, None, True,
        )
        create_calendar_event(
            100, 'genshin', 'Длинный ивент', '', 'event',
            date(2026, 11, 10), date(2026, 11, 20),
        )
        create_calendar_event(
            100, 'hsr', 'Баннер версии', '', 'banner',
            date(2026, 11, 18), date(2026, 11, 25),
        )

        response = self.client.get('/calendar?view=week&week=2026-11-16')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn('/static/calendar_timeline.js', response.text)
        self.assertIn('data-mode="week"', response.text)
        self.assertIn('data-start="2026-11-09"', response.text)
        self.assertIn('data-end="2026-11-29"', response.text)
        self.assertIn('data-anchor="2026-11-16"', response.text)
        self.assertIn('timeline-bar-label', response.text)
        self.assertIn('--game-color: #d8bc72', response.text)
        self.assertIn('--game-color: #a89be8', response.text)
        month = self.client.get('/calendar').text
        self.assertIn('href="/calendar?view=week', month)
        self.assertIn('href="/calendar?view=day', month)

        day = self.client.get('/calendar?view=day&day=2026-11-16')
        self.assertEqual(day.status_code, 200, day.text)
        self.assertIn('Дневная лента', day.text)
        self.assertIn('data-mode="day"', day.text)
        self.assertIn('data-start="2026-11-01"', day.text)
        self.assertIn('data-end="2026-12-01"', day.text)
        self.assertIn('data-anchor="2026-11-16"', day.text)
        self.assertEqual(day.text.count('data-timeline-date='), 31)
        self.assertIn('timeline-row-compact', day.text)

        page = build_calendar_timeline(
            date(2026, 11, 9), date(2026, 11, 29),
            today=date(2026, 11, 21), anchor_date=date(2026, 11, 16),
        )
        self.assertEqual(page['day_count'], 21)
        self.assertEqual(
            [row['label'] for row in page['rows']],
            ['Дни рождения', 'Genshin Impact', 'Honkai: Star Rail', 'Zenless Zone Zero'],
        )
        self.assertEqual(len(page['rows'][0]['bars']), 2)
        self.assertEqual(
            (page['rows'][1]['bars'][0]['column'], page['rows'][1]['bars'][0]['span']),
            (2, 11),
        )
        self.assertEqual(
            (page['rows'][2]['bars'][0]['column'], page['rows'][2]['bars'][0]['span']),
            (10, 8),
        )
        self.assertEqual(page['rows'][3]['event_count'], 0)

        fragment = self.client.get(
            '/calendar/timeline?start=2026-11-02&end=2026-11-29',
        )
        self.assertEqual(fragment.status_code, 200, fragment.text)
        payload = fragment.json()
        self.assertEqual(payload['start'], '2026-11-02')
        self.assertEqual(payload['end'], '2026-11-29')
        self.assertEqual(payload['html'].count('data-timeline-date='), 28)
        self.assertEqual(payload['category_count'], 4)
        self.assertIn('data-timeline-row="Дни рождения"', payload['html'])
        self.assertIn('data-timeline-row="Zenless Zone Zero"', payload['html'])

        filtered = build_calendar_timeline(
            date(2026, 11, 9), date(2026, 11, 29), game_code='genshin',
        )
        self.assertEqual(
            [row['label'] for row in filtered['rows']], ['Дни рождения', 'Genshin Impact'],
        )
        banners = build_calendar_timeline(
            date(2026, 11, 9), date(2026, 11, 29), event_type='banner',
        )
        self.assertEqual(
            [row['label'] for row in banners['rows']],
            ['Genshin Impact', 'Honkai: Star Rail', 'Zenless Zone Zero'],
        )
        self.assertEqual(banners['rows'][0]['event_count'], 0)
        players = build_calendar_timeline(
            date(2026, 11, 9), date(2026, 11, 29), event_type='player_birthday',
        )
        self.assertEqual([row['label'] for row in players['rows']], ['Дни рождения'])
        self.assertEqual(len(players['rows'][0]['bars']), 1)

        self.assertEqual(self.client.get('/calendar?view=unknown').status_code, 400)
        self.assertEqual(self.client.get('/calendar?view=week&week=invalid').status_code, 400)
        self.assertEqual(self.client.get('/calendar?view=day&day=invalid').status_code, 400)
        self.assertEqual(self.client.get(
            '/calendar/timeline?start=2026-11-29&end=2026-11-02',
        ).status_code, 400)
        self.assertEqual(self.client.get(
            '/calendar/timeline?start=2025-01-01&end=2026-12-31',
        ).status_code, 400)

    def test_activity_cycles_schedules_details_and_admin(self):
        from database.calendar_activity import (
            create_activity_cycle, delete_activity_cycle, list_calendar_activities,
            seed_calendar_activities, update_activity_cycle,
        )
        from services.tierlist_catalog import (
            get_tierlist_filter_options, list_tierlist_characters, reset_tierlist_catalog_cache,
        )
        from web.calendar import build_calendar_page
        from web.calendar_timeline import build_calendar_timeline

        queries.db(
            "INSERT INTO games (code, name) VALUES "
            "('zzz', 'Zenless Zone Zero'), ('endfield', 'Arknights: Endfield'), "
            "('hi3', 'Honkai Impact 3rd'), ('wuthering_waves', 'Wuthering Waves')"
        ).close()
        reset_tierlist_catalog_cache()
        seed_calendar_activities()
        activities = {
            activity['code']: activity for activity in list_calendar_activities('genshin')
        }
        elements = [
            option['id'] for option in get_tierlist_filter_options(['genshin'])['element'][:3]
        ]
        character = next(
            item for item in list_tierlist_characters(['genshin'])
            if item.get('availability', 'playable') == 'playable'
        )
        theater = create_activity_cycle(
            100, activities['theater']['id'],
            {'elements': elements, 'invited_characters': [character['id']]},
            cycle_month='2026-11',
        )
        self.assertEqual((theater['start_date'], theater['end_date']), (date(2026, 11, 1), date(2026, 11, 30)))
        abyss = create_activity_cycle(
            100, activities['abyss']['id'],
            {'first_half': 'Бонус первой половины', 'second_half': 'Бонус второй половины'},
            cycle_month='2026-11',
        )
        self.assertEqual((abyss['start_date'], abyss['end_date']), (date(2026, 11, 16), date(2026, 12, 15)))
        onslaught = create_activity_cycle(
            100, activities['onslaught']['id'], {'bosses': ['Босс 1', 'Босс 2', 'Босс 3']},
            patch_start='2026-11-10',
        )
        self.assertEqual((onslaught['start_date'], onslaught['end_date']), (date(2026, 11, 17), date(2026, 12, 21)))
        onslaught = update_activity_cycle(
            100, onslaught['id'], activities['onslaught']['id'],
            {'bosses': ['Босс 1', 'Босс 2', 'Босс 3']},
            start_date='2026-11-20', end_date='2026-12-24',
        )
        self.assertEqual(onslaught['start_date'], date(2026, 11, 20))

        timeline = build_calendar_timeline(
            date(2026, 11, 1), date(2026, 12, 31), game_code='genshin',
        )
        game_row = next(row for row in timeline['rows'] if row['label'] == 'Genshin Impact')
        cycle_bars = [bar for bar in game_row['bars'] if bar['cycle_id']]
        self.assertEqual(len(cycle_bars), 3)
        self.assertEqual([bar['row'] for bar in cycle_bars], [1, 2, 3])
        self.assertEqual(
            {bar['title']: bar['timeline_color'] for bar in cycle_bars},
            {'Театр Воображариума': '#a89be8', 'Витая Бездна': '#73b9e6', 'Мрачный натиск': '#d98164'},
        )
        compact = build_calendar_timeline(
            date(2026, 11, 1), date(2026, 12, 31), game_code='genshin', compact=True,
        )
        compact_rows = [row for row in compact['rows'] if row.get('compact')]
        self.assertEqual(len(compact_rows), 3)
        self.assertTrue(all(row['bars'][0]['cycle_id'] for row in compact_rows))
        month = build_calendar_page(2026, 11)
        self.assertTrue(any(item.get('cycle_id') for item in month['agenda']))

        theater_details = self.client.get(f'/calendar/cycles/{theater["id"]}')
        self.assertEqual(theater_details.status_code, 200, theater_details.text)
        self.assertIn(character['name'], theater_details.json()['html'])
        self.assertIn('Босс 3', self.client.get(f'/calendar/cycles/{onslaught["id"]}').json()['html'])
        self.assertIn('Бонус второй половины', self.client.get(f'/calendar/cycles/{abyss["id"]}').json()['html'])

        admin = self.client.get('/admin/calendar/cycles')
        self.assertEqual(admin.status_code, 200, admin.text)
        created = self.client.post('/admin/calendar/cycles', data={
            'activity_id': activities['theater']['id'], 'cycle_month': '2026-12',
            'elements': elements, 'invited_characters': [character['id']],
            'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(created.status_code, 303, created.text)
        self.assertIn('01.12.2026', self.client.get('/admin/calendar/cycles').text)
        delete_activity_cycle(100, theater['id'])
        self.assertEqual(self.client.get(f'/calendar/cycles/{theater["id"]}').status_code, 404)

    def test_developer_stream_admin_and_calendar(self):
        from database.calendar import get_calendar_event
        from web.calendar_timeline import build_calendar_timeline

        response = self._create_event('Стрим будущего обновления', 'genshin', 'stream')
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(get_calendar_event(1)['event_type'], 'stream')
        self.assertIn('Стрим разработчиков', self.client.get('/admin/calendar').text)

        calendar = self.client.get('/calendar?year=2026&month=11&type=stream')
        self.assertEqual(calendar.status_code, 200, calendar.text)
        self.assertIn('Стрим будущего обновления', calendar.text)
        self.assertIn('https://example.com/event', calendar.text)
        self.assertNotIn('Баннер новой версии', calendar.text)

        timeline = build_calendar_timeline(
            date(2026, 11, 1), date(2026, 12, 31), game_code='genshin', compact=True,
        )
        stream_row = next(row for row in timeline['rows'] if row.get('compact'))
        self.assertEqual(stream_row['bars'][0]['timeline_color'], '#8fc98f')
        self.assertEqual(stream_row['bars'][0]['row_span'], 1)
        self.assertEqual(stream_row['bars'][0]['url'], 'https://example.com/event')

    def test_banner_pairs_special_banner_and_ten_row_limit(self):
        from web.calendar_timeline import _row

        def event(title, start, end, kind='banner'):
            return {
                'id': title, 'kind': kind, 'title': title, 'subtitle': 'Genshin Impact',
                'url': None, 'external': False, 'start_date': start, 'end_date': end,
                'date_label': '', 'game_color': None, 'timeline_color': '#e5a3b5',
                'line_count': 2 if kind == 'banner' else 1,
            }

        range_start, range_end = date(2026, 11, 1), date(2026, 12, 31)
        events = [
            event('Мириады возможностей', date(2026, 11, 4), date(2026, 11, 24)),
            event('Песнь водам мира', date(2026, 11, 4), date(2026, 11, 24)),
            event('Гармония изобилия', date(2026, 11, 24), date(2026, 12, 15)),
            event('Молитва хроник Натлана', date(2026, 11, 24), date(2026, 12, 15)),
            event('Энциклопедия я-хо-хо', date(2026, 11, 24), date(2026, 12, 15)),
        ]
        row = _row('Genshin Impact', '', events, range_start, range_end)
        rows = {bar['title']: bar['row'] for bar in row['bars']}
        self.assertEqual(rows['Мириады возможностей'], rows['Гармония изобилия'])
        self.assertEqual(rows['Песнь водам мира'], rows['Энциклопедия я-хо-хо'])
        self.assertNotIn(
            rows['Молитва хроник Натлана'],
            {rows['Гармония изобилия'], rows['Энциклопедия я-хо-хо']},
        )

        crowded = _row(
            'Genshin Impact', '',
            [event(f'Ивент {index}', range_start, range_end, 'event') for index in range(11)],
            range_start, range_end,
        )
        self.assertEqual(crowded['event_rows'], 10)
        self.assertEqual(crowded['bars'][-1]['title'], 'Ещё событий: 2')

    def test_multiday_event_crosses_month_and_input_is_validated(self):
        from database.calendar import create_calendar_event

        create_calendar_event(
            100, 'genshin', 'Переходящий ивент', '', 'event',
            date(2026, 1, 30), date(2026, 2, 2),
        )
        february = self.client.get('/calendar?year=2026&month=2')
        self.assertEqual(february.status_code, 200, february.text)
        self.assertIn('Переходящий ивент', february.text)
        self.assertEqual(february.text.count('calendar-event-bar calendar-event-event'), 2)
        self.assertIn('30.01–02.02.2026', february.text)

        from web.calendar import build_calendar_page

        queries.set_birthday(100, 'player', 15, 11)
        create_calendar_event(
            100, 'genshin', 'Длинный ивент', '', 'event',
            date(2026, 11, 10), date(2026, 11, 20),
        )
        page = build_calendar_page(2026, 11, today=date(2026, 11, 15))
        bars = [bar for week in page['weeks'] for bar in week['event_bars']]
        self.assertEqual(
            [(bar['column'], bar['span'], bar['title']) for bar in bars],
            [(2, 6, 'Длинный ивент'), (1, 5, 'Длинный ивент')],
        )
        birthday_cell = page['weeks'][2]['days'][6]
        self.assertEqual(
            [event['kind'] for event in birthday_cell['events']], ['player_birthday'],
        )

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
