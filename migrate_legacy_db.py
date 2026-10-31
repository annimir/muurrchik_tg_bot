"""
Перенос старой SQLite-модели (user / character / subscriptions)
в PostgreSQL (users / tag / subscription).

Перед запуском примените database/database_structure.sql и остановите бота.
PostgreSQL из docker-compose доступен с хоста на localhost:5432.

    export POSTGRES_DSN='host=localhost port=5432 dbname=bot_db user=bot_user password=...'
    python migrate_legacy_db.py database.db --dry-run
    python migrate_legacy_db.py database.db

Скрипт идемпотентен: существующие пользователи и теги используются повторно,
подписки создаются или реактивируются. --dry-run откатывает все изменения.
"""

import argparse
import logging
import os
import sqlite3
import unicodedata
from pathlib import Path

import psycopg2

logger = logging.getLogger(__name__)

MERGE_DUPLICATE_IDS = {
    372: 371,
    337: 336,
}

REQUIRED_LEGACY_COLUMNS = {
    'user': {'id', 'tg_id', 'tag'},
    'character': {'id', 'name'},
    'subscriptions': {'user_id', 'character_id'},
}
REQUIRED_TARGET_TABLES = ('users', 'tag', 'subscription')


def normalize_name(name: str) -> str:
    return unicodedata.normalize('NFKC', name).casefold().strip()


def load_legacy(sqlite_path: Path):
    if not sqlite_path.is_file():
        raise FileNotFoundError(f'SQLite-файл не найден: {sqlite_path}')

    conn = sqlite3.connect(f'{sqlite_path.resolve().as_uri()}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for table, required_columns in REQUIRED_LEGACY_COLUMNS.items():
            columns = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
            missing = required_columns - columns
            if missing:
                raise ValueError(f'В SQLite-таблице {table} нет колонок: {", ".join(sorted(missing))}')

        users = conn.execute('SELECT id, tg_id, tag FROM user ORDER BY id').fetchall()
        characters = conn.execute('SELECT id, name FROM character ORDER BY id').fetchall()
        subscriptions = conn.execute(
            'SELECT user_id, character_id FROM subscriptions ORDER BY id'
        ).fetchall()
        return users, characters, subscriptions
    finally:
        conn.close()


def validate_target_schema(cur):
    for table in REQUIRED_TARGET_TABLES:
        cur.execute('SELECT to_regclass(%s) AS table_name', (f'public.{table}',))
        if cur.fetchone()[0] is None:
            raise RuntimeError(
                f'В PostgreSQL нет таблицы {table}. Сначала примените database/database_structure.sql'
            )


def migrate_users(cur, users):
    created = 0
    tg_ids = set()

    for row in users:
        if row['tg_id'] is None:
            raise ValueError(f'У legacy-пользователя id={row["id"]} отсутствует tg_id')
        tg_ids.add(row['tg_id'])
        cur.execute(
            'INSERT INTO users (tg_id, tag) VALUES (%s, %s) ON CONFLICT (tg_id) DO NOTHING',
            (row['tg_id'], row['tag']),
        )
        created += cur.rowcount

    cur.execute('SELECT id, tg_id FROM users WHERE tg_id = ANY(%s)', (list(tg_ids),))
    target_ids = {tg_id: user_id for user_id, tg_id in cur.fetchall()}

    missing = tg_ids - target_ids.keys()
    if missing:
        raise RuntimeError(f'Не удалось создать или найти пользователей с tg_id: {sorted(missing)}')

    old_to_target = {
        row['id']: target_ids[row['tg_id']]
        for row in users
    }
    logger.info('Пользователи: создано %d, уже существовали %d', created, len(tg_ids) - created)
    return old_to_target


def load_target_tags(cur):
    cur.execute('SELECT id, name FROM tag')
    tags = {}
    for tag_id, name in cur.fetchall():
        normalized = normalize_name(name)
        if normalized in tags and tags[normalized] != tag_id:
            raise RuntimeError(f'В PostgreSQL есть неоднозначные варианты имени тега: {name!r}')
        tags[normalized] = tag_id
    return tags


def migrate_tags(cur, characters):
    target_tags = load_target_tags(cur)
    source_tags = {}
    character_ids = {row['id'] for row in characters}
    old_to_tag = {}
    created = 0
    reused = 0
    merged_by_name = 0
    known_duplicates = 0

    for row in characters:
        old_id = row['id']
        if old_id in MERGE_DUPLICATE_IDS:
            continue

        name = row['name'].strip() if row['name'] else ''
        if not name:
            raise ValueError(f'У legacy-персонажа id={old_id} пустое имя')

        normalized = normalize_name(name)
        if normalized in source_tags:
            old_to_tag[old_id] = source_tags[normalized]
            merged_by_name += 1
            continue

        if normalized in target_tags:
            tag_id = target_tags[normalized]
            reused += 1
        else:
            cur.execute(
                "INSERT INTO tag (name, status, created_by) VALUES (%s, 'ACTIVE', NULL) RETURNING id",
                (name,),
            )
            tag_id = cur.fetchone()[0]
            target_tags[normalized] = tag_id
            created += 1

        source_tags[normalized] = tag_id
        old_to_tag[old_id] = tag_id

    for duplicate_id, canonical_id in MERGE_DUPLICATE_IDS.items():
        if duplicate_id not in character_ids:
            continue
        if canonical_id not in old_to_tag:
            raise ValueError(
                f'Не найден основной персонаж id={canonical_id} для дубля id={duplicate_id}'
            )
        old_to_tag[duplicate_id] = old_to_tag[canonical_id]
        known_duplicates += 1

    logger.info(
        'Теги: создано %d, уже существовали %d, объединено по имени %d, известных дублей %d',
        created,
        reused,
        merged_by_name,
        known_duplicates,
    )
    return old_to_tag


def migrate_subscriptions(cur, subscriptions, user_ids, tag_ids):
    pairs = set()
    orphaned = 0

    for row in subscriptions:
        user_id = user_ids.get(row['user_id'])
        tag_id = tag_ids.get(row['character_id'])
        if user_id is None or tag_id is None:
            orphaned += 1
            continue
        pairs.add((user_id, tag_id))

    for user_id, tag_id in sorted(pairs):
        cur.execute(
            '''
            INSERT INTO subscription (user_id, tag_id, active)
            VALUES (%s, %s, TRUE)
            ON CONFLICT (user_id, tag_id) DO UPDATE SET active = TRUE
            ''',
            (user_id, tag_id),
        )

    logger.info(
        'Подписки: перенесено или реактивировано %d, дублей в источнике %d, осиротевших %d',
        len(pairs),
        len(subscriptions) - len(pairs) - orphaned,
        orphaned,
    )


def migrate(sqlite_path: Path, dsn: str, dry_run: bool = False):
    users, characters, subscriptions = load_legacy(sqlite_path)
    logger.info(
        'Загружено из SQLite: %d пользователей, %d персонажей, %d подписок',
        len(users),
        len(characters),
        len(subscriptions),
    )

    conn = psycopg2.connect(dsn, connect_timeout=10)
    try:
        with conn.cursor() as cur:
            validate_target_schema(cur)
            user_ids = migrate_users(cur, users)
            tag_ids = migrate_tags(cur, characters)
            migrate_subscriptions(cur, subscriptions, user_ids, tag_ids)

        if dry_run:
            conn.rollback()
            logger.info('Пробный запуск успешен. Все изменения откачены.')
        else:
            conn.commit()
            logger.info('Миграция успешно завершена и зафиксирована.')
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description='Перенос users/tags/subscriptions из SQLite в Docker PostgreSQL'
    )
    parser.add_argument('sqlite_path', type=Path, help='Путь к старой SQLite-базе')
    parser.add_argument(
        '--dsn',
        default=os.getenv('POSTGRES_DSN'),
        help='DSN PostgreSQL; по умолчанию берётся из POSTGRES_DSN',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Выполнить и проверить перенос, но откатить транзакцию',
    )
    args = parser.parse_args()
    if not args.dsn:
        parser.error('Укажите --dsn или переменную окружения POSTGRES_DSN')
    return args


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
    args = parse_args()
    migrate(args.sqlite_path, args.dsn, dry_run=args.dry_run)


if __name__ == '__main__':
    main()
