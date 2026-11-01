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
    )
    sys.modules['config.config'] = config_module
    from database import queries


class PostgresTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        queries.db(
            '''
            TRUNCATE users, tag, games, flavor_roles, positions, affiliations, admins, chats,
            youtube_publications, youtube_api_usage
            RESTART IDENTITY CASCADE
            '''
        ).close()
