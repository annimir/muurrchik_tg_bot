import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries
from handlers.wishes.activity import is_paimon_praise
from services.wishes import perform_ten_wishes

MOSCOW_TZ = ZoneInfo('Europe/Moscow')


class PaimonPraiseTests(unittest.TestCase):
    def test_recognizes_praise_and_rejects_negation(self):
        self.assertTrue(is_paimon_praise('Паймон молодец!'))
        self.assertTrue(is_paimon_praise('Спасибо, Паймон'))
        self.assertTrue(is_paimon_praise('Паймон лучшая'))
        self.assertFalse(is_paimon_praise('Паймон не молодец'))
        self.assertFalse(is_paimon_praise('Просто сообщение'))


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class WishRewardDatabaseTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        from database import wish_rewards, wishes

        self.rewards = wish_rewards
        self.wishes = wishes
        self.user = queries.ensure_user(100, 'player')
        self.event = wishes.get_or_create_current_wish_event()
        self.banner = wishes.list_wish_banners(self.event['id'], active_only=True)[0]
        self.now = datetime.now(MOSCOW_TZ)

    def record(self, rule, source, now=None):
        return self.rewards.record_wish_activity(
            rule, self.user['id'], 'test', source, self.event['id'], now or self.now,
        )

    def test_daily_message_is_idempotent_and_resets_next_day(self):
        first = self.record('daily_message', 'message-1')
        duplicate = self.record('daily_message', 'message-1')
        second_today = self.record('daily_message', 'message-2')
        tomorrow = self.now + timedelta(days=1)
        early_level_two = self.record('daily_message', 'message-3', tomorrow)
        level_two = None
        for index in range(4, 8):
            level_two = self.record('daily_message', f'message-{index}', tomorrow)

        self.assertEqual(first['amount'], 1)
        self.assertIsNone(duplicate)
        self.assertIsNone(second_today)
        self.assertIsNone(early_level_two)
        self.assertEqual(level_two['amount'], 2)
        self.assertEqual(level_two['level'], 2)
        participant = self.wishes.get_participant(self.event['id'], self.user['id'])
        self.assertEqual(participant['bonus_earned'], 3)
        self.assertEqual(participant['remaining'], 303)

    def test_five_unique_photos_grant_only_once_per_day(self):
        grants = [self.record('five_daily_photos', f'photo-{index}') for index in range(5)]
        duplicate = self.record('five_daily_photos', 'photo-4')
        extra = self.record('five_daily_photos', 'photo-6')

        self.assertEqual([grant for grant in grants[:4]], [None] * 4)
        self.assertEqual(grants[4]['amount'], 10)
        self.assertIsNone(duplicate)
        self.assertIsNone(extra)
        progress = next(
            rule for rule in self.rewards.get_wish_reward_progress(
                self.event['id'], self.user['id'],
            ) if rule['code'] == 'five_daily_photos'
        )
        self.assertEqual(progress['progress'], 6)
        self.assertEqual(progress['level'], 1)
        self.assertEqual(progress['target_level'], 2)
        self.assertEqual(progress['threshold'], 10)
        self.assertFalse(progress['completed'])

    def test_photo_levels_increase_rewards_across_days(self):
        rewards = []
        for day, count in enumerate((5, 10, 20)):
            now = self.now + timedelta(days=day)
            for index in range(count):
                result = self.record('five_daily_photos', f'day-{day}-photo-{index}', now)
            rewards.append(result)

        self.assertEqual([reward['amount'] for reward in rewards], [10, 15, 20])
        self.assertEqual([reward['level'] for reward in rewards], [1, 2, 3])
        progress = next(
            rule for rule in self.rewards.get_wish_reward_progress(
                self.event['id'], self.user['id'],
            ) if rule['code'] == 'five_daily_photos'
        )
        self.assertTrue(progress['completed'])
        self.assertEqual(progress['level'], 3)
        self.assertEqual(progress['earned'], 45)

    def test_help_has_daily_and_monthly_limits(self):
        first = self.record('help_completed', 'request-1')
        same_day = self.record('help_completed', 'request-2')
        early_second = self.record('help_completed', 'request-3', self.now + timedelta(days=1))
        second = self.record('help_completed', 'request-4', self.now + timedelta(days=1))
        early_third = self.record('help_completed', 'request-5', self.now + timedelta(days=2))
        early_third_again = self.record('help_completed', 'request-6', self.now + timedelta(days=2))
        third = self.record('help_completed', 'request-7', self.now + timedelta(days=2))
        over_limit = self.record('help_completed', 'request-8', self.now + timedelta(days=3))

        self.assertEqual(first['amount'], 81)
        self.assertIsNone(same_day)
        self.assertIsNone(early_second)
        self.assertEqual(second['amount'], 122)
        self.assertIsNone(early_third)
        self.assertIsNone(early_third_again)
        self.assertEqual(third['amount'], 162)
        self.assertIsNone(over_limit)
        self.assertEqual(
            self.rewards.get_wish_reward_summary(self.event['id'], self.user['id'])['total'],
            365,
        )

    def test_new_tag_reward_requires_own_tag_from_today(self):
        tag = queries.create_tag('Fresh tag', created_by_tg_id=100)
        other_tag = queries.create_tag('Other tag', created_by_tg_id=200)

        reward = self.rewards.record_new_tag_activity(100, tag['id'], self.now)
        duplicate = self.rewards.record_new_tag_activity(100, tag['id'], self.now)
        not_owner = self.rewards.record_new_tag_activity(100, other_tag['id'], self.now)

        self.assertEqual(reward['amount'], 10)
        self.assertIsNone(duplicate)
        self.assertIsNone(not_owner)

    def test_first_ten_five_star_grants_level_rewards_and_updates_stats(self):
        self.rewards.update_wish_reward_rule(
            1000, 'first_ten_five_star', 50, 1, None, 1, True,
        )

        def force_five_star(items, state, count=10):
            self.assertEqual(count, 10)
            return perform_ten_wishes(items, state, rng=lambda: 0)

        with patch('database.wishes.perform_wish_batch', side_effect=force_five_star):
            result = self.wishes.perform_wishes(
                self.event['id'], self.user['id'], self.banner['id'],
            )

        self.assertEqual(result['drops'][0]['rarity'], 5)
        self.assertEqual(result['rewards'][0]['amount'], 100)
        self.assertEqual(result['rewards'][0]['level'], 3)
        self.assertEqual(result['remaining'], 390)
        participant = self.wishes.get_participant(self.event['id'], self.user['id'])
        self.assertEqual(participant['used'], 10)
        self.assertEqual(participant['total_allowance'], 400)
        stats = self.wishes.get_wish_participant_stats(self.event['id'])[0]
        self.assertEqual(stats['used'], 10)
        self.assertEqual(stats['bonus_earned'], 100)

    def test_first_ten_level_matches_five_star_count(self):
        self.rewards.update_wish_reward_rule(
            1000, 'first_ten_five_star', 50, 1, None, 1, True,
        )
        reward = self.rewards.record_wish_activity(
            'first_ten_five_star', self.user['id'], 'wish_event', self.event['id'],
            self.event['id'], self.now, progress_value=3,
        )
        duplicate = self.rewards.record_wish_activity(
            'first_ten_five_star', self.user['id'], 'wish_event', self.event['id'],
            self.event['id'], self.now, progress_value=3,
        )

        self.assertEqual(reward['amount'], 100)
        self.assertEqual(reward['level'], 3)
        self.assertIsNone(duplicate)

    def test_single_five_star_does_not_trigger_first_ten_reward(self):
        from services.wishes import perform_wishes as perform_wish_batch

        self.rewards.update_wish_reward_rule(
            1000, 'first_ten_five_star', 50, 1, None, 1, True,
        )

        def force_five_star(items, state, count=1):
            return perform_wish_batch(items, state, count=count, rng=lambda: 0)

        with patch('database.wishes.perform_wish_batch', side_effect=force_five_star):
            result = self.wishes.perform_wishes(
                self.event['id'], self.user['id'], self.banner['id'], count=1,
            )

        self.assertEqual(result['drops'][0]['rarity'], 5)
        self.assertEqual(result['rewards'], [])
        self.assertEqual(result['remaining'], 299)

    async def test_telegram_message_awards_daily_activity_and_praise_silently(self):
        from unittest.mock import AsyncMock, MagicMock

        from handlers.wishes.activity import wish_activity_message_handler

        update = MagicMock()
        update.edited_message = None
        update.effective_user.id = 100
        update.effective_user.is_bot = False
        update.effective_user.username = 'player'
        update.effective_user.full_name = 'Player'
        update.effective_chat.id = -100
        update.effective_message.text = 'Паймон молодец!'
        update.effective_message.message_id = 10
        update.effective_message.message_thread_id = None
        update.effective_message.via_bot = None
        update.effective_message.forward_origin = None
        update.effective_message.reply_text = AsyncMock()

        await wish_activity_message_handler(update, MagicMock())
        await wish_activity_message_handler(update, MagicMock())

        participant = self.wishes.get_participant(self.event['id'], self.user['id'])
        self.assertEqual(participant['bonus_earned'], 2)
        self.assertEqual(update.effective_message.reply_text.await_count, 0)

    def test_admin_updates_reward_rule(self):
        levels = [
            {'level': 1, 'reward': 2, 'threshold': 1},
            {'level': 2, 'reward': 4, 'threshold': 3},
            {'level': 3, 'reward': 6, 'threshold': 5},
        ]
        self.rewards.update_wish_reward_rule(
            1000, 'daily_message', 2, 1, 1, None, True, levels=levels,
        )
        try:
            rule = next(
                rule for rule in self.rewards.list_wish_reward_rules()
                if rule['code'] == 'daily_message'
            )
            self.assertEqual(rule['reward'], 2)
            self.assertEqual(rule['levels'][1]['reward'], 4)
            self.assertEqual(self.record('daily_message', 'message-1')['amount'], 2)
            with self.assertRaises(ValueError):
                self.rewards.update_wish_reward_rule(
                    1000, 'daily_message', 2, 1, 1, None, True,
                    levels=[
                        {'level': 1, 'reward': 2, 'threshold': 1},
                        {'level': 2, 'reward': 1, 'threshold': 3},
                        {'level': 3, 'reward': 6, 'threshold': 5},
                    ],
                )
        finally:
            self.rewards.update_wish_reward_rule(
                1000, 'daily_message', 1, 1, 1, None, True,
                levels=[
                    {'level': 1, 'reward': 1, 'threshold': 1},
                    {'level': 2, 'reward': 2, 'threshold': 5},
                    {'level': 3, 'reward': 3, 'threshold': 10},
                ],
            )
