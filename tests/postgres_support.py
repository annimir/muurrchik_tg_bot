import os
import sys
import types
import unittest

TEST_POSTGRES_DSN = os.getenv('TEST_POSTGRES_DSN')
queries = None

if TEST_POSTGRES_DSN:
    config_module = types.ModuleType('config.config')
    config_module.config = types.SimpleNamespace(pg_dsn=TEST_POSTGRES_DSN)
    sys.modules['config.config'] = config_module
    from database import queries


class PostgresTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        queries.db(
            '''
            TRUNCATE users, tag, games, flavor_roles, positions, affiliations, admins, chats
            RESTART IDENTITY CASCADE
            '''
        ).close()
