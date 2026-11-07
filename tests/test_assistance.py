import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries
from database import assistance


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class AssistanceTestCase(PostgresTestCase):
    def setUp(self):
        super().setUp()
        queries.db(
            "INSERT INTO games (code, name) VALUES ('genshin', 'Genshin Impact') ON CONFLICT DO NOTHING"
        ).close()
        queries.db(
            '''
            INSERT INTO game_modes (game_code, name) VALUES
                ('genshin', 'Театр воображариума'), ('genshin', 'Витая бездна'),
                ('genshin', 'Мрачный натиск')
            ON CONFLICT DO NOTHING
            '''
        ).close()
        self.requester = queries.ensure_user(100, 'requester')
        self.first_helper = queries.ensure_user(200, 'helper-one')
        self.second_helper = queries.ensure_user(300, 'helper-two')
        self.mode = assistance.list_game_modes('genshin')[0]

    def enable_helper(self, user):
        assistance.set_helper_mode(user['id'], self.mode['id'], True)
        assistance.set_helper_dm_available(user['id'], True)

    def create_request(self):
        result = assistance.create_help_request(self.requester['id'], self.mode['id'], 900, 77)
        self.assertEqual(result['status'], 'created')
        for helper in result['helpers']:
            assistance.create_help_offer(result['request']['id'], helper['id'])
        return result['request']


class AssistanceDatabaseTests(AssistanceTestCase):
    def test_modes_and_no_helpers(self):
        self.assertEqual(len(assistance.list_game_modes('genshin')), 3)
        result = assistance.create_help_request(self.requester['id'], self.mode['id'], 900, None)
        self.assertEqual(result['status'], 'no_helpers')

    def test_self_is_excluded_and_duplicate_is_rejected(self):
        self.enable_helper(self.requester)
        self.enable_helper(self.first_helper)

        result = assistance.create_help_request(self.requester['id'], self.mode['id'], 900, None)

        self.assertEqual([row['id'] for row in result['helpers']], [self.first_helper['id']])
        duplicate = assistance.create_help_request(self.requester['id'], self.mode['id'], 900, None)
        self.assertEqual(duplicate['status'], 'already_exists')

    def test_all_helpers_declined(self):
        self.enable_helper(self.first_helper)
        self.enable_helper(self.second_helper)
        request = self.create_request()

        first = assistance.decline_help_offer(request['id'], self.first_helper['id'])
        self.assertFalse(first['all_declined'])
        second = assistance.decline_help_offer(request['id'], self.second_helper['id'])

        self.assertTrue(second['all_declined'])
        self.assertEqual(assistance.get_help_request(request['id'])['status'], 'REJECTED')
        self.assertIsNone(assistance.claim_help_request(request['id'], self.first_helper['id']))

    def test_first_claim_wins_and_request_is_completed(self):
        self.enable_helper(self.first_helper)
        self.enable_helper(self.second_helper)
        request = self.create_request()

        claimed = assistance.claim_help_request(request['id'], self.first_helper['id'])
        self.assertEqual(claimed['status'], 'SCHEDULING')
        self.assertTrue(assistance.finalize_help_offers(request['id']))
        self.assertIsNone(assistance.claim_help_request(request['id'], self.second_helper['id']))
        scheduled = datetime.now(timezone.utc) + timedelta(days=1)
        confirming = assistance.schedule_help_request(
            request['id'], self.first_helper['id'], scheduled,
        )
        self.assertEqual(confirming['status'], 'CONFIRMING')
        self.assertIsNone(assistance.schedule_help_request(
            request['id'], self.second_helper['id'], scheduled,
        ))
        self.assertIsNone(assistance.confirm_help_request(request['id'], self.first_helper['id']))
        assigned = assistance.confirm_help_request(request['id'], self.requester['id'])
        self.assertEqual(assigned['status'], 'ASSIGNED')
        completed = assistance.complete_help_request(request['id'], self.requester['id'])
        self.assertEqual(completed['status'], 'COMPLETED')
        summary = assistance.get_helper_public_summary(self.first_helper['id'])
        self.assertEqual(summary['completed_count'], 1)

    def test_pause_and_expiry(self):
        self.enable_helper(self.first_helper)
        assistance.set_helper_paused(self.first_helper['id'], True)
        result = assistance.create_help_request(self.requester['id'], self.mode['id'], 900, None)
        self.assertEqual(result['status'], 'no_helpers')
        assistance.set_helper_paused(self.first_helper['id'], False)
        request = self.create_request()
        queries.db(
            "UPDATE help_requests SET expires_at = now() - INTERVAL '1 minute' WHERE id = %s",
            (request['id'],),
        ).close()

        expired = assistance.expire_help_requests()

        self.assertEqual([row['id'] for row in expired], [request['id']])
        self.assertEqual(assistance.get_help_request(request['id'])['status'], 'EXPIRED')


class AssistanceHandlerTests(AssistanceTestCase):
    async def test_assist_selection_creates_request_and_sends_private_offer(self):
        from handlers.assistance.requests import assist_command, assist_select_callback

        self.enable_helper(self.first_helper)
        message = AsyncMock()
        tg_user = type('User', (), {'id': 100, 'username': 'requester', 'full_name': 'Requester'})()
        update = type('Update', (), {
            'effective_user': tg_user, 'effective_message': message,
        })()
        context = type('Context', (), {'bot': SimpleNamespaceForBot(), 'user_data': {}})()

        await assist_command(update, context)

        query = AsyncMock()
        query.from_user = tg_user
        query.message.chat.id = 900
        query.message.message_thread_id = 77
        query.message.message_id = 555
        query.data = message.reply_text.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
        update.callback_query = query
        await assist_select_callback(update, context)
        query.data = query.edit_message_text.await_args.kwargs['reply_markup'].inline_keyboard[0][0].callback_data
        await assist_select_callback(update, context)

        request = queries.db('SELECT * FROM help_requests').one()
        self.assertEqual(request['requester_user_id'], self.requester['id'])
        self.assertEqual(request['request_message_id'], 555)
        offers = assistance.list_request_offers(request['id'])
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]['status'], 'PENDING')
        self.assertEqual(context.bot.send_message.await_args.args[0], 200)

    async def test_offer_accept_time_confirm_and_complete_handlers(self):
        from handlers.assistance.requests import (
            assist_offer_callback, assist_request_callback, assist_time_callback,
        )

        self.enable_helper(self.first_helper)
        request = self.create_request()
        queries.db(
            'UPDATE help_requests SET request_message_id = 555 WHERE id = %s', (request['id'],),
        ).close()
        bot = SimpleNamespaceForBot()
        context = type('Context', (), {'bot': bot, 'user_data': {}})()
        helper_query = AsyncMock()
        helper_query.data = f'assist_offer:accept:{request["id"]}'
        helper_query.from_user.id = 200
        helper_query.from_user.username = 'helper-one'
        update = type('Update', (), {'callback_query': helper_query, 'effective_user': helper_query.from_user})()

        await assist_offer_callback(update, context)

        self.assertIn('Укажите', helper_query.edit_message_text.await_args.args[0])
        time_query = AsyncMock()
        time_query.data = f'assist_time:plus2:{request["id"]}'
        time_query.from_user = helper_query.from_user
        update.callback_query = time_query
        await assist_time_callback(update, context)
        self.assertEqual(assistance.get_help_request(request['id'])['status'], 'CONFIRMING')
        self.assertEqual(bot.edit_message_text.await_args.kwargs['message_id'], 555)

        requester_query = AsyncMock()
        requester_query.from_user.id = 100
        requester_query.from_user.username = 'requester'
        requester_query.data = f'assist_request:confirm:{request["id"]}'
        update.callback_query = requester_query
        await assist_request_callback(update, context)
        self.assertEqual(assistance.get_help_request(request['id'])['status'], 'ASSIGNED')

        requester_query.data = f'assist_request:complete:{request["id"]}'
        await assist_request_callback(update, context)
        self.assertEqual(assistance.get_help_request(request['id'])['status'], 'COMPLETED')


class SimpleNamespaceForBot:
    def __init__(self):
        self.send_message = AsyncMock(return_value=type('Message', (), {'message_id': 1})())
        self.edit_message_text = AsyncMock()


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class AssistanceWebIntegrationTests(AssistanceTestCase):
    def setUp(self):
        super().setUp()
        from web.app import create_app

        self.client = TestClient(create_app())
        from web.auth import SESSION_COOKIE, create_admin_session

        queries.add_admin(1000)
        token, self.csrf = create_admin_session(1000)
        self.client.cookies.set(SESSION_COOKIE, token)

    def tearDown(self):
        self.client.close()

    def test_admin_and_public_helper_profile(self):
        self.enable_helper(self.first_helper)
        request = self.create_request()

        page = self.client.get('/admin/assistance')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Витая бездна', page.text)
        self.assertIn('helper-one', page.text)
        self.assertIn('#1', page.text)
        profile = self.client.get(f'/users/{self.first_helper["id"]}')
        self.assertIn('Помогатор', profile.text)
        self.assertIn('Genshin Impact', profile.text)
        self.assertIn(self.mode['name'], profile.text)

        response = self.client.post('/admin/assistance/modes', data={
            'game_code': 'genshin', 'name': 'New mode', 'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        duplicate = self.client.post('/admin/assistance/modes', data={
            'game_code': 'genshin', 'name': 'new mode', 'csrf_token': self.csrf,
        })
        self.assertEqual(duplicate.status_code, 400)
        new_mode = assistance.list_game_modes('genshin', active_only=False)[-1]
        response = self.client.post(f'/admin/assistance/modes/{new_mode["id"]}/active', data={
            'active': 'false', 'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertFalse(assistance.get_game_mode(new_mode['id'])['is_active'])

        response = self.client.post(f'/admin/assistance/helpers/{self.first_helper["id"]}/active', data={
            'active': 'false', 'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertFalse(assistance.get_helper_profile(self.first_helper['id'])['is_active'])
        response = self.client.post(f'/admin/assistance/requests/{request["id"]}/cancel', data={
            'csrf_token': self.csrf,
        }, follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(assistance.get_help_request(request['id'])['status'], 'CANCELLED')
        self.assertEqual(self.client.get('/admin/assistance?status=UNKNOWN').status_code, 400)
