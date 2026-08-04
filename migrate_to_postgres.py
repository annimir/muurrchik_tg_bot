import sqlite3
import psycopg2
from config import config

SQLITE_PATH = 'database/database.db'

def get_sqlite_connection():
    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_pg_connection():
    return psycopg2.connect(config.pg_dsn)

def migrate_users(sqlite_conn, pg_conn):
    rows = sqlite_conn.execute('SELECT tg_id, tag FROM user').fetchall()
    with pg_conn.cursor() as cur:
        for row in rows:
            cur.execute(
                '''
                INSERT INTO users (tg_id, tag)
                VALUES (%s, %s)
                ON CONFLICT (tg_id) DO NOTHING
                ''',
                (row['tg_id'], row['tag'])
            )
    pg_conn.commit()
    print(f'users: перенесено {len(rows)} строк')

def migrate_characters(sqlite_conn, pg_conn):
    rows = sqlite_conn.execute('SELECT name, description FROM character').fetchall()
    with pg_conn.cursor() as cur:
        for row in rows:
            cur.execute(
                '''
                INSERT INTO character (name, description)
                VALUES (%s, %s)
                ON CONFLICT (name) DO NOTHING
                ''',
                (row['name'], row['description'])
            )
    pg_conn.commit()
    print(f'character: перенесено {len(rows)} строк')

def migrate_subscriptions(sqlite_conn, pg_conn):
    # старые связи через старые id -> достаём tg_id и name, чтобы не зависеть от числовых id
    rows = sqlite_conn.execute(
        '''
        SELECT u.tg_id AS tg_id, c.name AS character_name
        FROM subscriptions s
        JOIN user u ON s.user_id = u.id
        JOIN character c ON s.character_id = c.id
        '''
    ).fetchall()
    migrated = 0
    with pg_conn.cursor() as cur:
        for row in rows:
            cur.execute('SELECT id FROM users WHERE tg_id = %s', (row['tg_id'],))
            user = cur.fetchone()

            cur.execute('SELECT id FROM character WHERE name = %s', (row['character_name'],))
            character = cur.fetchone()

            if not user or not character:
                print(f'Пропущена подписка: tg_id={row["tg_id"]}, character={row["character_name"]} '
                      f'(пользователь или персонаж не найден в Postgres)')
                continue

            cur.execute(
                '''
                INSERT INTO subscriptions (user_id, character_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                ''',
                (user[0], character[0])
            )
            migrated += 1

    pg_conn.commit()
    print(f'subscriptions: перенесено {migrated} из {len(rows)} строк')

def main():
    sqlite_conn = get_sqlite_connection()
    pg_conn = get_pg_connection()
    try:
        migrate_users(sqlite_conn, pg_conn)
        migrate_characters(sqlite_conn, pg_conn)
        migrate_subscriptions(sqlite_conn, pg_conn)
        print('Миграция завершена успешно.')
    except Exception:
        pg_conn.rollback()
        raise
    finally:
        sqlite_conn.close()
        pg_conn.close()

if __name__ == '__main__':
    main()