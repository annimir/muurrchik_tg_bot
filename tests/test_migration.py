import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from migrate_legacy_db import migrate
from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class MigrationIntegrationTests(PostgresTestCase):
    def create_legacy_db(self, directory):
        path = Path(directory) / 'legacy.db'
        conn = sqlite3.connect(path)
        conn.executescript('''
            CREATE TABLE user (id INTEGER PRIMARY KEY, tg_id INTEGER NOT NULL, tag TEXT NOT NULL);
            CREATE TABLE character (id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT);
            CREATE TABLE subscriptions (
                id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, character_id INTEGER NOT NULL
            );
        ''')
        conn.executemany('INSERT INTO user VALUES (?, ?, ?)', [(1, 100, 'user'), (2, 200, 'other')])
        conn.executemany('INSERT INTO character (id, name) VALUES (?, ?)', [
            (10, 'Alpha'), (11, ' alpha '), (371, 'Kirena'), (372, 'Kirena duplicate'),
        ])
        conn.executemany('INSERT INTO subscriptions (user_id, character_id) VALUES (?, ?)', [
            (1, 10), (2, 11), (1, 371), (1, 372), (999, 10), (1, 999),
        ])
        conn.commit()
        conn.close()
        return path

    def test_migration_and_dry_run(self):
        with TemporaryDirectory(dir='.') as directory:
            legacy_path = self.create_legacy_db(directory)

            migrate(legacy_path, TEST_POSTGRES_DSN, dry_run=True)
            self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM users').one()['cnt'], 0)

            migrate(legacy_path, TEST_POSTGRES_DSN)
            migrate(legacy_path, TEST_POSTGRES_DSN)

        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM users').one()['cnt'], 2)
        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM tag').one()['cnt'], 2)
        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM subscription WHERE active').one()['cnt'], 3)
