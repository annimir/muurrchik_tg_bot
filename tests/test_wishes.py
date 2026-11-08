import unittest
from datetime import datetime

from services.wishes import _five_star_probability, perform_ten_wishes
from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


def wish_items():
    return [
        {'name': 'Featured 5', 'rarity': 5, 'item_type': 'character', 'featured': True},
        {'name': 'Standard 5', 'rarity': 5, 'item_type': 'character', 'featured': False},
        {'name': 'Featured 4', 'rarity': 4, 'item_type': 'character', 'featured': True},
        {'name': 'Standard 4', 'rarity': 4, 'item_type': 'weapon', 'featured': False},
        {'name': 'Weapon 3', 'rarity': 3, 'item_type': 'weapon', 'featured': False},
    ]


class WishEngineTests(unittest.TestCase):
    def test_soft_and_hard_pity_probabilities(self):
        self.assertEqual(_five_star_probability(73), 0.006)
        self.assertAlmostEqual(_five_star_probability(74), 0.066)
        self.assertEqual(_five_star_probability(90), 1.0)

    def test_ninetieth_pull_is_five_star_and_loss_sets_guarantee(self):
        state, drops = perform_ten_wishes(wish_items(), {'pity5': 89}, rng=lambda: 0.999)

        self.assertEqual(len(drops), 10)
        self.assertEqual(drops[0]['name'], 'Standard 5')
        self.assertEqual(drops[0]['pity5_at'], 90)
        self.assertTrue(state['featured5_guaranteed'])
        self.assertEqual(state['radiance_streak'], 1)

    def test_guaranteed_featured_five_star(self):
        state, drops = perform_ten_wishes(
            wish_items(), {'featured5_guaranteed': True}, rng=lambda: 0,
        )

        self.assertEqual(drops[0]['name'], 'Featured 5')
        self.assertFalse(state['featured5_guaranteed'])

    def test_four_star_guarantee_and_featured_loss(self):
        state, drops = perform_ten_wishes(wish_items(), {'pity4': 9}, rng=lambda: 0.999)

        self.assertEqual(drops[0]['rarity'], 4)
        self.assertEqual(drops[0]['name'], 'Standard 4')
        self.assertTrue(state['featured4_guaranteed'])

    def test_capturing_radiance_after_three_loss_cycles(self):
        state, drops = perform_ten_wishes(wish_items(), {'radiance_streak': 3}, rng=lambda: 0)

        self.assertTrue(drops[0]['radiant'])
        self.assertEqual(drops[0]['name'], 'Featured 5')
        self.assertEqual(state['radiance_streak'], 0)


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class WishDatabaseTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        from database import wishes

        self.wishes = wishes
        self.user = queries.ensure_user(100, 'player')
        self.event = wishes.get_or_create_current_wish_event()
        self.banner = wishes.list_wish_banners(self.event['id'], active_only=True)[0]

    def test_ten_wishes_update_participant_and_stats(self):
        result = self.wishes.perform_wishes(self.event['id'], self.user['id'], self.banner['id'])

        self.assertEqual(len(result['drops']), 10)
        self.assertEqual(result['remaining'], 290)
        participant = self.wishes.get_participant(self.event['id'], self.user['id'])
        self.assertEqual(participant['used'], 10)
        stats = self.wishes.get_wish_participant_stats(self.event['id'])[0]
        self.assertEqual(stats['used'], 10)
        self.assertEqual(
            stats['five_star_count'] + stats['four_star_count'] + stats['three_star_count'], 10,
        )
        self.assertEqual(len(self.wishes.get_recent_drops(self.event['id'], self.user['id'])), 10)

    def test_default_catalog_is_localized(self):
        from pathlib import Path

        items = self.wishes.list_wish_items(self.banner['id'])
        self.assertEqual(len(items), 90)
        all_items = {
            item['name']
            for banner in self.wishes.list_wish_banners(self.event['id'])
            for item in self.wishes.list_wish_items(banner['id'])
        }
        self.assertEqual(len(all_items), 91)
        for item in items:
            with self.subTest(item=item['name']):
                self.assertTrue(item['display_name'])
                self.assertTrue(item['image_url'].startswith('/static/wishes/items/')
                                and item['image_url'].endswith('.webp'))
                self.assertTrue(Path('web' + item['image_url']).is_file())
        self.assertIn('Mitya', {item['name'] for item in items})
        mitya = next(item for item in items if item['name'] == 'Mitya')
        self.assertEqual(mitya['display_name'], 'Митя')

    def test_allowance_and_winners(self):
        self.wishes.set_wish_allowance(1000, self.event['id'], 10)
        self.assertEqual(self.wishes.calculate_wish_winners(self.event['id']), [])
        self.wishes.perform_wishes(self.event['id'], self.user['id'], self.banner['id'])

        winners = self.wishes.calculate_wish_winners(self.event['id'])

        self.assertEqual(len(winners), 2)
        self.assertEqual({row['kind'] for row in winners}, {'LUCKIEST', 'UNLUCKIEST'})
        self.assertEqual(winners[0]['user_id'], self.user['id'])

    def test_restart_archives_and_resets_participants(self):
        self.wishes.perform_wishes(self.event['id'], self.user['id'], self.banner['id'])
        old_item_count = len(self.wishes.list_wish_items(self.banner['id']))

        new_event = self.wishes.restart_wish_event(1000, self.event['id'])

        self.assertNotEqual(new_event['id'], self.event['id'])
        self.assertEqual(new_event['period'], datetime.now().strftime('%Y-%m'))
        self.assertEqual(self.wishes.get_wish_event(self.event['id'])['status'], 'ARCHIVED')
        self.assertIsNone(self.wishes.get_participant(new_event['id'], self.user['id']))
        new_banner = self.wishes.list_wish_banners(new_event['id'])[0]
        self.assertEqual(len(self.wishes.list_wish_items(new_banner['id'])), old_item_count)

    def test_banner_and_item_management(self):
        banner_id = self.wishes.create_wish_banner(1000, self.event['id'], 'Test banner')
        item_id = self.wishes.add_wish_item(
            1000, banner_id, 'Test character', 5, 'character', True,
        )
        self.assertTrue(self.wishes.get_wish_banner(banner_id))
        self.wishes.set_wish_banner_active(1000, banner_id, False)
        self.assertFalse(self.wishes.get_wish_banner(banner_id)['is_active'])
        self.wishes.delete_wish_item(1000, item_id)
        self.assertIsNone(queries.db('SELECT 1 FROM wish_items WHERE id = %s', (item_id,)).one())


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class WishWebIntegrationTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        from database import wishes
        from fastapi.testclient import TestClient
        from web.app import create_app
        from web.auth import SESSION_COOKIE, create_admin_session

        self.wishes = wishes
        self.user = queries.ensure_user(100, 'player')
        queries.add_admin(100)
        token, self.csrf = create_admin_session(100)
        self.client = TestClient(create_app())
        self.client.cookies.set(SESSION_COOKIE, token)
        self.event = wishes.get_or_create_current_wish_event()
        self.banner = wishes.list_wish_banners(self.event['id'], active_only=True)[0]

    def tearDown(self):
        self.client.close()

    def test_admin_pull_and_event_controls(self):
        page = self.client.get('/wishes')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Myriad Patterns Unfold', page.text)
        self.assertIn('Участники', page.text)

        response = self.client.post(f'/wishes/{self.event["id"]}/pull', data={
            'banner_id': self.banner['id'], 'csrf_token': self.csrf,
        })
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload['drops']), 10)
        self.assertEqual(payload['remaining'], 290)
        self.assertEqual(payload['stats'][0]['used'], 10)

        admin_page = self.client.get('/admin/wishes')
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn('player', admin_page.text)
        response = self.client.post('/admin/wishes/allowance', data={
            'allowance': 20, 'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.wishes.get_wish_event(self.event['id'])['pull_allowance'], 20)
        response = self.client.post('/admin/wishes/winners', data={
            'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/admin/wishes/restart', data={
            'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.wishes.get_wish_event(self.event['id'])['status'], 'ARCHIVED')

    def test_admin_updates_reward_settings(self):
        from database.wish_rewards import list_wish_reward_rules, update_wish_reward_rule

        page = self.client.get('/admin/wishes')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Задания Паймон', page.text)
        response = self.client.post('/admin/wishes/rewards/daily_message', data={
            'reward': 2, 'threshold': 1, 'daily_limit': 1, 'monthly_limit': '',
            'is_active': 'true', 'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        try:
            rule = next(
                rule for rule in list_wish_reward_rules() if rule['code'] == 'daily_message'
            )
            self.assertEqual(rule['reward'], 2)
            self.assertEqual(rule['daily_limit'], 1)
        finally:
            update_wish_reward_rule(100, 'daily_message', 1, 1, 1, None, True)

    def test_wish_images_have_correct_mime_type(self):
        response = self.client.get('/static/wishes/items/mitya.webp')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['content-type'], 'image/webp')

    def test_wishes_require_telegram_session(self):
        from fastapi.testclient import TestClient
        from web.app import create_app

        with TestClient(create_app()) as client:
            response = client.get('/wishes', follow_redirects=False)
            login = client.get('/wishes/login')
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['location'], '/wishes/login')
        self.assertEqual(login.status_code, 200)
        self.assertIn('Войти через Telegram', login.text)

    def test_non_admin_can_pull_but_not_open_admin_controls(self):
        from web.auth import SESSION_COOKIE, create_admin_session

        player = queries.ensure_user(200, 'regular_player')
        token, csrf = create_admin_session(200)
        self.client.cookies.set(SESSION_COOKIE, token)

        page = self.client.get('/wishes')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Тестовый режим для всех игроков', page.text)
        self.assertIn('action="/wishes/logout"', page.text)
        self.assertNotIn('action="/admin/logout"', page.text)
        response = self.client.post(f'/wishes/{self.event["id"]}/pull', data={
            'banner_id': self.banner['id'], 'csrf_token': csrf,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['remaining'], 290)
        participant = self.wishes.get_participant(self.event['id'], player['id'])
        self.assertEqual(participant['used'], 10)

        admin_page = self.client.get('/admin/wishes', follow_redirects=False)
        self.assertEqual(admin_page.status_code, 303)
        self.assertEqual(admin_page.headers['location'], '/admin/login')

    def test_telegram_login_creates_player_session(self):
        from unittest.mock import patch

        from fastapi.testclient import TestClient
        from web.app import create_app

        with TestClient(create_app()) as client:
            with patch('web.routes.wishes.verify_telegram_login', return_value=True):
                response = client.get('/wishes/login/telegram', params={
                    'id': 200, 'username': 'new_player', 'first_name': 'New',
                }, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers['location'], '/wishes')
            page = client.get('/wishes')

        self.assertEqual(page.status_code, 200)
        self.assertIn('new_player', page.text)
        self.assertEqual(queries.get_user_by_tg_id(200)['tag'], 'new_player')
