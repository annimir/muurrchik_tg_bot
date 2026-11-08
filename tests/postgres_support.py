import os
import sys
import types
import unittest

TEST_POSTGRES_DSN = os.getenv('TEST_POSTGRES_DSN')
queries = None

if TEST_POSTGRES_DSN:
    config_module = types.ModuleType('config.config')
    config_module.config = types.SimpleNamespace(
        pg_dsn=TEST_POSTGRES_DSN,
        youtube_enabled=False,
        youtube_api_key=None,
        youtube_channel_handle='@muuurrchik',
        youtube_target_chat_id=200,
        youtube_check_interval_seconds=14400,
        bot_token='123456:test-token',
        web_secret_key='test-secret-key',
        web_session_ttl_seconds=28800,
        web_media_cache_dir='data/test-media',
        web_public_base_url='http://testserver',
        web_telegram_bot_username='test_bot',
        web_secure_cookies=False,
    )
    sys.modules['config.config'] = config_module
    from database import queries


class PostgresTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        queries.db(
            '''
            TRUNCATE users, tag, games, positions, affiliations, admins, chats,
            youtube_publications, youtube_api_usage, admin_audit_log, wish_events
            RESTART IDENTITY CASCADE
            '''
        ).close()
        queries.db(
            "UPDATE wish_reward_rules SET is_active = FALSE WHERE code = 'first_ten_five_star'"
        ).close()
