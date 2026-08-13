from database import Database
from config import config

tables_path = 'database/database_structure.sql'

db = Database(config.pg_dsn)
db.execute_file(tables_path)

# ---------- USERS / AUTH ----------

def get_user_by_tg_id(tg_id):
    return db('SELECT * FROM users WHERE tg_id = %s', (tg_id,)).one()


def create_user(tg_id, tag):
    db('INSERT INTO users (tg_id, tag) VALUES (%s, %s)', (tg_id, tag)).close()


def update_user_tag(tg_id, new_tag):
    db('UPDATE users SET tag = %s WHERE tg_id = %s', (new_tag, tg_id)).close()


def get_user_by_username(username):
    return db('SELECT id, tg_id FROM users WHERE tag = %s', (username,)).one()


def get_all_users():
    return db('SELECT * FROM users').all()


# ---------- LANGUAGE ----------

def get_user_language(tg_id) -> str:
    row = db('SELECT language FROM users WHERE tg_id = %s', (tg_id,)).one()
    return row['language'] if row else 'RU'


def set_user_language(tg_id, language: str):
    db('UPDATE users SET language = %s WHERE tg_id = %s', (language, tg_id)).close()


# ---------- BIRTHDAYS (старая chat_id-модель — упростится на Этапе D) ----------

def set_birthday(tg_id, tag, chat_id, day, month, year=None):
    user = get_user_by_tg_id(tg_id)
    if not user:
        create_user(tg_id, tag)

    query = '''
        INSERT INTO birthdays (user_id, chat_id, day, month, year)
        VALUES ((SELECT id FROM users WHERE tg_id = %s), %s, %s, %s, %s)
        ON CONFLICT (user_id, chat_id)
        DO UPDATE SET day = EXCLUDED.day, month = EXCLUDED.month, year = EXCLUDED.year
    '''
    db(query, (tg_id, chat_id, day, month, year)).close()


def get_birthday(tg_id, chat_id):
    query = '''
        SELECT b.day, b.month, b.year
        FROM birthdays b
        JOIN users u ON u.id = b.user_id
        WHERE u.tg_id = %s AND b.chat_id = %s
    '''
    return db(query, (tg_id, chat_id)).one()


def delete_birthday(tg_id, chat_id):
    query = '''
        DELETE FROM birthdays
        WHERE user_id = (SELECT id FROM users WHERE tg_id = %s) AND chat_id = %s
    '''
    db(query, (tg_id, chat_id)).close()


def get_todays_birthdays(day, month):
    query = '''
        SELECT u.tg_id, u.tag, b.chat_id, b.year
        FROM birthdays b
        JOIN users u ON u.id = b.user_id
        WHERE b.day = %s AND b.month = %s
    '''
    return db(query, (day, month)).all()


def get_chat_birthdays(chat_id):
    query = '''
        SELECT u.tg_id, u.tag, b.day, b.month, b.year
        FROM birthdays b
        JOIN users u ON u.id = b.user_id
        WHERE b.chat_id = %s
        ORDER BY b.month, b.day
    '''
    return db(query, (chat_id,)).all()


# ---------- CHATS / MEMBERSHIP (Этап 3 первого раунда) ----------

def upsert_chat(chat_id, title):
    query = '''
        INSERT INTO chats (chat_id, title, is_active)
        VALUES (%s, %s, TRUE)
        ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title, is_active = TRUE
    '''
    db(query, (chat_id, title)).close()


def deactivate_chat(chat_id):
    db('UPDATE chats SET is_active = FALSE WHERE chat_id = %s', (chat_id,)).close()


def get_active_chats():
    return db('SELECT chat_id, title FROM chats WHERE is_active = TRUE').all()


def upsert_membership(user_id, chat_id, is_member: bool):
    query = '''
        INSERT INTO user_chat_memberships (user_id, chat_id, is_member, updated_at)
        VALUES (%s, %s, %s, now())
        ON CONFLICT (user_id, chat_id) DO UPDATE SET is_member = EXCLUDED.is_member, updated_at = now()
    '''
    db(query, (user_id, chat_id, is_member)).close()


def has_any_active_membership(user_id) -> bool:
    row = db(
        'SELECT 1 FROM user_chat_memberships WHERE user_id = %s AND is_member = TRUE LIMIT 1',
        (user_id,),
    ).one()
    return row is not None


def mark_user_left_all(user_id):
    db(
        'UPDATE users SET left_at = now(), deletion_warned_at = NULL WHERE id = %s AND left_at IS NULL',
        (user_id,),
    ).close()


def mark_user_returned(user_id):
    db('UPDATE users SET left_at = NULL, deletion_warned_at = NULL WHERE id = %s', (user_id,)).close()


def get_users_pending_warning():
    query = '''
        SELECT id, tg_id, language
        FROM users
        WHERE left_at IS NOT NULL AND deletion_warned_at IS NULL
          AND left_at <= now() - interval '6 months'
    '''
    return db(query).all()


def mark_user_warned(user_id):
    db('UPDATE users SET deletion_warned_at = now() WHERE id = %s', (user_id,)).close()


def get_users_pending_deletion():
    query = '''
        SELECT id, tg_id
        FROM users
        WHERE deletion_warned_at IS NOT NULL AND deletion_warned_at <= now() - interval '7 days'
    '''
    return db(query).all()


def delete_user_completely(user_id):
    """
    ИСПРАВЛЕНО: раньше здесь был отдельный вызов delete_orphaned_bot_characters(),
    который фильтровал по character.source — колонки, которой больше нет
    после Этапа A. Теперь character.owner_user_id -> users.id имеет
    ON DELETE CASCADE, так что удаление пользователя само каскадно
    удаляет его персонажей. Отдельный шаг не нужен.
    """
    db('DELETE FROM users WHERE id = %s', (user_id,)).close()


# ---------- FLAVOR ROLES (Этап 4 первого раунда) ----------

def get_all_flavor_roles():
    return db('SELECT id, name FROM flavor_roles').all()


def add_flavor_role(name):
    query = '''
        INSERT INTO flavor_roles (name) VALUES (%s)
        ON CONFLICT (name) DO NOTHING
        RETURNING id
    '''
    row = db(query, (name,)).one()
    return row['id'] if row else None


def get_flavor_role_by_name(name):
    return db('SELECT id, name FROM flavor_roles WHERE lower(name) = lower(%s)', (name,)).one()


def get_users_with_role(role_id):
    return db('SELECT id, tg_id FROM users WHERE flavor_role_id = %s', (role_id,)).all()


def delete_flavor_role(role_id):
    db('DELETE FROM flavor_roles WHERE id = %s', (role_id,)).close()


def set_user_flavor_role(user_id, role_id):
    db('UPDATE users SET flavor_role_id = %s WHERE id = %s', (role_id, user_id)).close()


def get_user_flavor_role(user_id):
    query = '''
        SELECT fr.id, fr.name
        FROM users u
        JOIN flavor_roles fr ON fr.id = u.flavor_role_id
        WHERE u.id = %s
    '''
    return db(query, (user_id,)).one()


def get_users_without_role():
    return db('SELECT id, tg_id FROM users WHERE flavor_role_id IS NULL').all()


# ---------- GAMES (Этап 5 первого раунда) ----------

def get_user_games(user_id) -> set[str]:
    rows = db('SELECT game_code FROM user_games WHERE user_id = %s', (user_id,)).all()
    return {row['game_code'] for row in rows}


def toggle_user_game(user_id, game_code):
    existing = db(
        'SELECT 1 FROM user_games WHERE user_id = %s AND game_code = %s', (user_id, game_code)
    ).one()
    if existing:
        db('DELETE FROM user_games WHERE user_id = %s AND game_code = %s', (user_id, game_code)).close()
    else:
        db('INSERT INTO user_games (user_id, game_code) VALUES (%s, %s)', (user_id, game_code)).close()


# ---------- TAG (Этап A) ----------

def get_tag_by_name(name):
    return db('SELECT * FROM tag WHERE lower(name) = lower(%s)', (name,)).one()


def create_tag(name, created_by_tg_id=None):
    query = '''
        INSERT INTO tag (name, status, created_by)
        VALUES (%s, 'ACTIVE', %s)
        RETURNING *
    '''
    return db(query, (name, created_by_tg_id)).one()


def get_all_tags():
    return db('SELECT * FROM tag').all()


def get_active_tags():
    return db("SELECT * FROM tag WHERE status = 'ACTIVE'").all()


def search_tags(search_line: str):
    if not search_line:
        return db("SELECT name, id FROM tag WHERE status = 'ACTIVE'").all()
    query = "SELECT name, id FROM tag WHERE status = 'ACTIVE' AND name LIKE %s"
    return db(query, (f"{search_line}%",)).all()


def touch_tag_last_used(tag_id):
    db('UPDATE tag SET last_used_at = now() WHERE id = %s', (tag_id,)).close()


def rename_tag(tag_id, new_name):
    db('UPDATE tag SET name = %s WHERE id = %s', (new_name, tag_id)).close()


def add_tag_alias(tag_id, alias):
    db('INSERT INTO tag_alias (tag_id, alias) VALUES (%s, %s)', (tag_id, alias)).close()


def get_all_tag_aliases():
    query = '''
        SELECT ta.alias, t.name
        FROM tag_alias ta
        JOIN tag t ON t.id = ta.tag_id
        WHERE t.status = 'ACTIVE'
    '''
    return db(query).all()


def set_tag_status(tag_id, status):
    """Добавлено на Этапе B1."""
    valid = {'ACTIVE', 'DELETED', 'BLOCKED'}
    if status not in valid:
        raise ValueError(f'Недопустимый статус: {status}')
    db('UPDATE tag SET status = %s WHERE id = %s', (status, tag_id)).close()

def find_any_tag_or_alias_owner(name):
    """
    Точное совпадение (без учёта регистра) с именем тега или его алиасом,
    НЕЗАВИСИМО от статуса. Нужно поймать коллизию с DELETED/BLOCKED тегом,
    которого нет в TagStorage-кэше — иначе create_tag()/add_tag_alias()
    упадёт на UNIQUE-ограничении вместо понятного сообщения пользователю.
    """
    query = '''
        SELECT name, status FROM tag WHERE lower(name) = lower(%s)
        UNION
        SELECT t.name, t.status
        FROM tag_alias ta
        JOIN tag t ON t.id = ta.tag_id
        WHERE lower(ta.alias) = lower(%s)
    '''
    return db(query, (name, name)).one()

# ---------- SUBSCRIPTION (Этап A) ----------
# ИСПРАВЛЕНО: все функции принимают tg_id (а не внутренний users.id),
# как и весь остальной проект (see set_birthday и т.д.) — раньше в
# первом черновике Этапа A была нестыковка: subscribe_tag/unsubscribe_tag
# ожидали внутренний id, а вызывающий код передавал бы tg_id. Теперь
# соответствие единообразно по всему файлу.

def subscribe_tag(tg_id, tag_id):
    query = '''
        INSERT INTO subscription (user_id, tag_id, active)
        VALUES ((SELECT id FROM users WHERE tg_id = %s), %s, TRUE)
        ON CONFLICT (user_id, tag_id) DO UPDATE SET active = TRUE
    '''
    db(query, (tg_id, tag_id)).close()


def unsubscribe_tag(tg_id, tag_id):
    query = '''
        UPDATE subscription SET active = FALSE
        WHERE user_id = (SELECT id FROM users WHERE tg_id = %s) AND tag_id = %s
    '''
    db(query, (tg_id, tag_id)).close()


def unsubscribe_all_tags(tg_id):
    query = '''
        UPDATE subscription SET active = FALSE
        WHERE user_id = (SELECT id FROM users WHERE tg_id = %s)
    '''
    db(query, (tg_id,)).close()


def count_active_subscriptions(tg_id) -> int:
    query = '''
        SELECT COUNT(*) AS cnt
        FROM subscription s
        JOIN users u ON u.id = s.user_id
        WHERE u.tg_id = %s AND s.active = TRUE
    '''
    return db(query, (tg_id,)).one()['cnt']


def get_user_subscriptions(tg_id):
    query = '''
        SELECT t.id, t.name
        FROM subscription s
        JOIN tag t ON t.id = s.tag_id
        JOIN users u ON u.id = s.user_id
        WHERE u.tg_id = %s AND s.active = TRUE AND t.status = 'ACTIVE'
    '''
    return db(query, (tg_id,)).all()


def get_tag_subscribers(tag_id):
    query = '''
        SELECT u.tg_id, u.tag AS username
        FROM subscription s
        JOIN users u ON u.id = s.user_id
        WHERE s.tag_id = %s AND s.active = TRUE
    '''
    return db(query, (tag_id,)).all()

def log_tag_usage(tag_id, telegram_message_id, author_tg_id, media_type):
    query = '''
        INSERT INTO tag_usage (tag_id, telegram_message_id, author_tg_id, media_type)
        VALUES (%s, %s, %s, %s)
    '''
    db(query, (tag_id, telegram_message_id, author_tg_id, media_type)).close()

def get_tag_subscriber_count(tag_id) -> int:
    row = db("SELECT COUNT(*) AS cnt FROM subscription WHERE tag_id = %s AND active = TRUE", (tag_id,)).one()
    return row['cnt']


def get_tag_usage_count(tag_id, days=30) -> int:
    query = '''
        SELECT COUNT(*) AS cnt FROM tag_usage
        WHERE tag_id = %s AND used_at >= now() - (%s * INTERVAL '1 day')
    '''
    return db(query, (tag_id, days)).one()['cnt']


def get_top_tags_by_subscribers(limit: int | None = None):
    """
    ИСПРАВЛЕНО (B5): раньше топ считался в Python-цикле — по запросу
    get_tag_subscribers() на КАЖДЫЙ тег отдельно (N+1). Теперь один
    агрегирующий SQL-запрос.
    """
    query = '''
        SELECT t.name, COUNT(s.id) AS cnt
        FROM tag t
        LEFT JOIN subscription s ON s.tag_id = t.id AND s.active = TRUE
        WHERE t.status = 'ACTIVE'
        GROUP BY t.name
        ORDER BY cnt DESC
    '''
    if limit:
        return db(query + ' LIMIT %s', (limit,)).all()
    return db(query).all()


def get_top_tags_by_usage(days: int = 30, limit: int | None = None):
    query = '''
        SELECT t.name, COUNT(tu.id) AS cnt
        FROM tag t
        LEFT JOIN tag_usage tu ON tu.tag_id = t.id AND tu.used_at >= now() - (%s * INTERVAL '1 day')
        WHERE t.status = 'ACTIVE'
        GROUP BY t.name
        ORDER BY cnt DESC
    '''
    if limit:
        return db(query + ' LIMIT %s', (days, limit)).all()
    return db(query, (days,)).all()


def get_top_users_by_subscriptions(limit: int | None = None):
    """ИСПРАВЛЕНО (B5): тот же N+1, что и у тегов, теперь одним запросом."""
    query = '''
        SELECT u.tag AS username, COUNT(s.id) AS cnt
        FROM users u
        LEFT JOIN subscription s ON s.user_id = u.id AND s.active = TRUE
        GROUP BY u.tag
        ORDER BY cnt DESC
    '''
    if limit:
        return db(query + ' LIMIT %s', (limit,)).all()
    return db(query).all()