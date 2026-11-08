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
        tomorrow = self.record(
            'daily_message', 'message-3', self.now + timedelta(days=1),
        )

        self.assertEqual(first['amount'], 1)
        self.assertIsNone(duplicate)
        self.assertIsNone(second_today)
        self.assertEqual(tomorrow['amount'], 1)
        participant = self.wishes.get_participant(self.event['id'], self.user['id'])
        self.assertEqual(participant['bonus_earned'], 2)
        self.assertEqual(participant['remaining'], 302)

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
        self.assertEqual(progress['progress'], 5)
        self.assertTrue(progress['completed'])

    def test_help_has_daily_and_monthly_limits(self):
        first = self.record('help_completed', 'request-1')
        same_day = self.record('help_completed', 'request-2')
        second = self.record('help_completed', 'request-3', self.now + timedelta(days=1))
        third = self.record('help_completed', 'request-4', self.now + timedelta(days=2))
        over_limit = self.record('help_completed', 'request-5', self.now + timedelta(days=3))

        self.assertEqual(first['amount'], 81)
        self.assertIsNone(same_day)
        self.assertEqual(second['amount'], 81)
        self.assertEqual(third['amount'], 81)
        self.assertIsNone(over_limit)
        self.assertEqual(
            self.rewards.get_wish_reward_summary(self.event['id'], self.user['id'])['total'],
            243,
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

    def test_first_ten_five_star_grants_fifty_and_updates_stats(self):
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
        self.assertEqual(result['rewards'][0]['amount'], 50)
        self.assertEqual(result['remaining'], 340)
        participant = self.wishes.get_participant(self.event['id'], self.user['id'])
        self.assertEqual(participant['used'], 10)
        self.assertEqual(participant['total_allowance'], 350)
        stats = self.wishes.get_wish_participant_stats(self.event['id'])[0]
        self.assertEqual(stats['used'], 10)
        self.assertEqual(stats['bonus_earned'], 50)

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
        self.rewards.update_wish_reward_rule(
            1000, 'daily_message', 2, 1, 1, None, True,
        )
        try:
            rule = next(
                rule for rule in self.rewards.list_wish_reward_rules()
                if rule['code'] == 'daily_message'
            )
            self.assertEqual(rule['reward'], 2)
            self.assertEqual(self.record('daily_message', 'message-1')['amount'], 2)
            with self.assertRaises(ValueError):
                self.rewards.update_wish_reward_rule(
                    1000, 'daily_message', 0, 1, 1, None, True,
                )
        finally:
            self.rewards.update_wish_reward_rule(
                1000, 'daily_message', 1, 1, 1, None, True,
            )
