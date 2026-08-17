from database import Database
from config import config

tables_path = 'database/database_structure.sql'

db = Database(config.pg_dsn)
db.execute_file(tables_path)


# ==================== USERS / AUTH ====================

def get_user_by_tg_id(tg_id):
    return db('SELECT * FROM users WHERE tg_id = %s', (tg_id,)).one()


def get_user_by_id(user_id):
    return db('SELECT * FROM users WHERE id = %s', (user_id,)).one()


def create_user(tg_id, tag):
    db('INSERT INTO users (tg_id, tag) VALUES (%s, %s)', (tg_id, tag)).close()


def update_user_tag(tg_id, new_tag):
    db('UPDATE users SET tag = %s WHERE tg_id = %s', (new_tag, tg_id)).close()


def get_user_by_username(username):
    return db('SELECT id, tg_id FROM users WHERE tag = %s', (username,)).one()


def get_all_users():
    return db('SELECT * FROM users').all()


# ==================== ADMINS ====================

def get_all_admin_ids() -> set[int]:
    rows = db('SELECT tg_id FROM admins').all()
    return {row['tg_id'] for row in rows}


def add_admin(tg_id):
    db('INSERT INTO admins (tg_id) VALUES (%s) ON CONFLICT DO NOTHING', (tg_id,)).close()


def remove_admin(tg_id):
    db('DELETE FROM admins WHERE tg_id = %s', (tg_id,)).close()


def count_admins() -> int:
    return db('SELECT COUNT(*) AS cnt FROM admins').one()['cnt']


def bootstrap_admin_if_empty(tg_id):
    if count_admins() == 0:
        add_admin(tg_id)


# ==================== LANGUAGE ====================

def get_user_language(tg_id) -> str:
    row = db('SELECT language FROM users WHERE tg_id = %s', (tg_id,)).one()
    return row['language'] if row else 'RU'


def set_user_language(tg_id, language: str):
    db('UPDATE users SET language = %s WHERE tg_id = %s', (language, tg_id)).close()


# ==================== BIRTHDAYS — пользователи ===================

def set_birthday(tg_id, tag, day, month, year=None):
    user = get_user_by_tg_id(tg_id)
    if not user:
        create_user(tg_id, tag)

    query = '''
        INSERT INTO birthdays (user_id, day, month, year)
        VALUES ((SELECT id FROM users WHERE tg_id = %s), %s, %s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET day = EXCLUDED.day, month = EXCLUDED.month, year = EXCLUDED.year
    '''
    db(query, (tg_id, day, month, year)).close()


def get_birthday(tg_id):
    query = '''
        SELECT b.day, b.month, b.year
        FROM birthdays b
        JOIN users u ON u.id = b.user_id
        WHERE u.tg_id = %s
    '''
    return db(query, (tg_id,)).one()


def delete_birthday(tg_id):
    query = 'DELETE FROM birthdays WHERE user_id = (SELECT id FROM users WHERE tg_id = %s)'
    db(query, (tg_id,)).close()


def get_todays_birthdays(day, month):
    query = '''
        SELECT u.tg_id, u.tag
        FROM birthdays b
        JOIN users u ON u.id = b.user_id
        WHERE b.day = %s AND b.month = %s
    '''
    return db(query, (day, month)).all()


def get_all_birthdays():
    query = '''
        SELECT u.tg_id, u.tag, b.day, b.month, b.year
        FROM birthdays b
        JOIN users u ON u.id = b.user_id
        ORDER BY b.month, b.day
    '''
    return db(query).all()


# ==================== BIRTHDAYS — персонажи (Этап D4) ====================

def get_todays_character_birthdays(day, month):
    query = '''
        SELECT c.id, c.name, u.tg_id AS owner_tg_id, u.tag AS owner_username
        FROM character c
        JOIN users u ON u.id = c.owner_user_id
        WHERE EXTRACT(DAY FROM c.birth_date)::int = %s
          AND EXTRACT(MONTH FROM c.birth_date)::int = %s
    '''
    return db(query, (day, month)).all()


# ==================== CHATS / ЧЛЕНСТВО ====================

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


# ==================== АВТООЧИСТКА НЕАКТИВНЫХ ====================

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
    db('DELETE FROM users WHERE id = %s', (user_id,)).close()


# ==================== FLAVOR ROLES ====================

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


# ==================== GAMES ====================

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


# ==================== TAG ====================

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
    valid = {'ACTIVE', 'DELETED', 'BLOCKED'}
    if status not in valid:
        raise ValueError(f'Недопустимый статус: {status}')
    db('UPDATE tag SET status = %s WHERE id = %s', (status, tag_id)).close()


def find_any_tag_or_alias_owner(name):
    query = '''
        SELECT name, status FROM tag WHERE lower(name) = lower(%s)
        UNION
        SELECT t.name, t.status
        FROM tag_alias ta
        JOIN tag t ON t.id = ta.tag_id
        WHERE lower(ta.alias) = lower(%s)
    '''
    return db(query, (name, name)).one()


# ==================== SUBSCRIPTION ====================

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


# ==================== TAG_USAGE / СТАТИСТИКА ====================

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


# ==================== CHARACTER ====================

def is_character_name_taken(name) -> bool:
    row = db('SELECT 1 FROM character WHERE lower(name) = lower(%s)', (name,)).one()
    return row is not None


def get_user_character_count(user_id) -> int:
    row = db('SELECT COUNT(*) AS cnt FROM character WHERE owner_user_id = %s', (user_id,)).one()
    return row['cnt']


def get_user_characters(user_id):
    query = '''
        SELECT * FROM character
        WHERE owner_user_id = %s
        ORDER BY is_primary DESC, created_at
    '''
    return db(query, (user_id,)).all()


def get_character_by_id(character_id):
    return db('SELECT * FROM character WHERE id = %s', (character_id,)).one()


def create_character_row(owner_user_id, name, birth_date, photo_file_id, description, is_primary):
    query = '''
        INSERT INTO character (owner_user_id, name, birth_date, photo_file_id, description, is_primary)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING *
    '''
    return db(query, (owner_user_id, name, birth_date, photo_file_id, description, is_primary)).one()


def apply_character_edit(character_id, description=None, photo_file_id=None, birth_date=None):
    fields = []
    params = []

    if description is not None:
        fields.append('description = %s')
        params.append(description)
    if photo_file_id is not None:
        fields.append('photo_file_id = %s')
        params.append(photo_file_id)
    if birth_date is not None:
        fields.append('birth_date = %s')
        params.append(birth_date)

    if not fields:
        return

    params.append(character_id)
    db(f'UPDATE character SET {", ".join(fields)} WHERE id = %s', tuple(params)).close()


def set_character_primary(user_id, character_id):
    db('UPDATE character SET is_primary = FALSE WHERE owner_user_id = %s', (user_id,)).close()
    db('UPDATE character SET is_primary = TRUE WHERE id = %s AND owner_user_id = %s', (character_id, user_id)).close()


def get_primary_character(user_id):
    return db('SELECT * FROM character WHERE owner_user_id = %s AND is_primary = TRUE', (user_id,)).one()


# ==================== CHARACTER REQUESTS ====================

def create_character_request(
    request_type, user_id, chat_id, character_id=None,
    name=None, birth_date=None, description=None, photo_file_id=None,
    requester_display_name=None, requester_username=None,
):
    query = '''
        INSERT INTO character_requests
            (request_type, user_id, character_id, chat_id, name, birth_date, description, photo_file_id,
             requester_display_name, requester_username)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    '''
    row = db(query, (
        request_type, user_id, character_id, chat_id, name, birth_date, description, photo_file_id,
        requester_display_name, requester_username,
    )).one()
    return row['id']


def get_character_request_by_id(request_id):
    return db('SELECT * FROM character_requests WHERE id = %s', (request_id,)).one()


def update_character_request_status(request_id, status):
    db(
        'UPDATE character_requests SET status = %s, resolved_at = now() WHERE id = %s',
        (status, request_id),
    ).close()


def update_character_request_field(request_id, field, value):
    allowed = {'name', 'birth_date', 'description', 'photo_file_id'}
    if field not in allowed:
        raise ValueError(f'Недопустимое поле: {field}')
    db(f'UPDATE character_requests SET {field} = %s WHERE id = %s', (value, request_id)).close()


def get_user_character_requests(user_id):
    query = 'SELECT * FROM character_requests WHERE user_id = %s ORDER BY created_at DESC'
    return db(query, (user_id,)).all()


# ==================== USER_CARD ====================

def get_user_card(user_id):
    return db('SELECT * FROM user_card WHERE user_id = %s', (user_id,)).one()


def upsert_user_card_bio(user_id, bio):
    query = '''
        INSERT INTO user_card (user_id, bio)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET bio = EXCLUDED.bio
    '''
    db(query, (user_id, bio)).close()


# ==================== CARD REQUESTS ====================

def create_card_request(user_id, chat_id, bio, requester_display_name=None, requester_username=None):
    query = '''
        INSERT INTO card_requests (user_id, chat_id, bio, requester_display_name, requester_username)
        VALUES (%s, %s, %s, %s, %s)
        RETURNING id
    '''
    row = db(query, (user_id, chat_id, bio, requester_display_name, requester_username)).one()
    return row['id']


def get_card_request_by_id(request_id):
    return db('SELECT * FROM card_requests WHERE id = %s', (request_id,)).one()


def update_card_request_status(request_id, status):
    db(
        'UPDATE card_requests SET status = %s, resolved_at = now() WHERE id = %s',
        (status, request_id),
    ).close()


def update_card_request_bio(request_id, bio):
    db('UPDATE card_requests SET bio = %s WHERE id = %s', (bio, request_id)).close()


def get_user_card_requests(user_id):
    query = 'SELECT * FROM card_requests WHERE user_id = %s ORDER BY created_at DESC'
    return db(query, (user_id,)).all()


# ==================== ЗАЯВКИ — ВЗЯТИЕ В РАБОТУ / ОЧЕРЕДЬ ====================

_REQUEST_TABLES = {'character': 'character_requests', 'card': 'card_requests'}


def claim_request(request_type, request_id, admin_tg_id):
    table = _REQUEST_TABLES[request_type]
    db(f'UPDATE {table} SET claimed_by = %s, claimed_at = now() WHERE id = %s', (admin_tg_id, request_id)).close()


def release_request(request_type, request_id):
    table = _REQUEST_TABLES[request_type]
    db(f'UPDATE {table} SET claimed_by = NULL, claimed_at = NULL WHERE id = %s', (request_id,)).close()


def save_request_notification(request_type, request_id, admin_tg_id, message_id):
    query = '''
        INSERT INTO request_notifications (request_type, request_id, admin_tg_id, message_id)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (request_type, request_id, admin_tg_id) DO UPDATE SET message_id = EXCLUDED.message_id
    '''
    db(query, (request_type, request_id, admin_tg_id, message_id)).close()


def get_request_notifications(request_type, request_id):
    query = 'SELECT admin_tg_id, message_id FROM request_notifications WHERE request_type = %s AND request_id = %s'
    return db(query, (request_type, request_id)).all()


def get_pending_unclaimed_requests():
    query = '''
        SELECT 'character' AS request_type, id, name AS label, created_at
        FROM character_requests
        WHERE status = 'pending' AND claimed_by IS NULL
        UNION ALL
        SELECT 'card' AS request_type, id, LEFT(bio, 40) AS label, created_at
        FROM card_requests
        WHERE status = 'pending' AND claimed_by IS NULL
        ORDER BY created_at
    '''
    return db(query).all()


def get_my_claimed_requests(admin_tg_id):
    query = '''
        SELECT 'character' AS request_type, id, name AS label, claimed_at
        FROM character_requests
        WHERE status = 'pending' AND claimed_by = %s
        UNION ALL
        SELECT 'card' AS request_type, id, LEFT(bio, 40) AS label, claimed_at
        FROM card_requests
        WHERE status = 'pending' AND claimed_by = %s
        ORDER BY claimed_at
    '''
    return db(query, (admin_tg_id, admin_tg_id)).all()