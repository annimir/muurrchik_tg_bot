from database import Database
from config import config

tables_path = 'database/database_structure.sql'

db = Database(config.pg_dsn)
db.execute_file(tables_path)

def get_user_by_tg_id(tg_id):
    query = '''
        SELECT tg_id, tag
        FROM users
        WHERE tg_id = %s
    '''
    return db(query, (tg_id,)).one()

def create_user(tg_id, tag):
    query = 'INSERT INTO users (tg_id, tag) VALUES (%s, %s)'
    db(query, (tg_id, tag)).close()

def update_user_tag(tg_id, new_tag):
    query = 'UPDATE users SET tag = %s WHERE tg_id = %s'
    db(query, (new_tag, tg_id)).close()

def create_character(character_name):
    query = 'INSERT INTO character (name) VALUES (%s)'
    db(query, (character_name,)).close()

def get_character_by_name(character_name):
    query = '''
        SELECT id, name, description
        FROM character
        WHERE name = %s
    '''
    return db(query, (character_name,)).one()

def get_all_characters():
    query = '''
        SELECT *
        FROM character
    '''
    return db(query).all()

def get_all_users():
    query = '''
        SELECT *
        FROM users
    '''
    return db(query).all()

def get_character_subscribers(character_name):
    query = '''
        SELECT u.tg_id, u.tag
        FROM users u
        JOIN subscriptions s ON u.id = s.user_id
        JOIN character c ON s.character_id = c.id
        WHERE c.name = %s
    '''
    return db(query, (character_name,)).all()

def search_characters(for_character_name_search_line):
    if not for_character_name_search_line:
        query = '''
            SELECT name, description
            FROM character
        '''
        return db(query).all()

    query = '''
        SELECT name, description
        FROM character
        WHERE name LIKE %s
    '''
    search_term = f"{for_character_name_search_line}%"
    return db(query, (search_term,)).all()

def subscribe_character(character_name, user_tg_id):
    character = db('SELECT id FROM character WHERE name = %s', (character_name,)).one()
    if not character:
        return None
    character_id = character['id']

    user = db('SELECT id FROM users WHERE tg_id = %s', (user_tg_id,)).one()
    if not user:
        return None
    user_id = user['id']

    is_sub = db(
        'SELECT user_id FROM subscriptions WHERE user_id = %s AND character_id = %s',
        (user_id, character_id)
    ).one()

    if not is_sub:
        db(
            'INSERT INTO subscriptions (user_id, character_id) VALUES (%s, %s)',
            (user_id, character_id)
        ).close()

def unsubscribe_character(character_name, user_tg_id):
    character = db('SELECT id FROM character WHERE name = %s', (character_name,)).one()
    if not character:
        return None
    character_id = character['id']

    user = db('SELECT id FROM users WHERE tg_id = %s', (user_tg_id,)).one()
    if not user:
        return None
    user_id = user['id']

    db(
        'DELETE FROM subscriptions WHERE user_id = %s AND character_id = %s',
        (user_id, character_id)
    ).close()

def get_user_subscriptions(user_tg_id):
    query = '''
        SELECT c.name, c.description
        FROM character c
        JOIN subscriptions s ON c.id = s.character_id
        JOIN users u ON s.user_id = u.id
        WHERE u.tg_id = %s
    '''
    return db(query, (user_tg_id,)).all()

def delete_character(character_name):
    db('DELETE FROM character WHERE name = %s', (character_name,)).close()

def update_character_name(character_id, character_name):
    db('UPDATE character SET name = %s WHERE id = %s', (character_name, character_id)).close()

def set_birthday(tg_id, tag, chat_id, day, month, year=None):
    user = get_user_by_tg_id(tg_id)
    if not user:
        create_user(tg_id, tag)
        user = get_user_by_tg_id(tg_id)

    user_row = db('SELECT id FROM users WHERE tg_id = %s', (tg_id,)).one()
    user_id = user_row['id']

    query = '''
        INSERT INTO birthdays (user_id, chat_id, day, month, year)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (user_id, chat_id)
        DO UPDATE SET day = EXCLUDED.day, month = EXCLUDED.month, year = EXCLUDED.year
    '''
    db(query, (user_id, chat_id, day, month, year)).close()


def get_todays_birthdays(day, month):
    query = '''
        SELECT u.tg_id, u.tag, b.chat_id, b.year
        FROM birthdays b
        JOIN users u ON u.id = b.user_id
        WHERE b.day = %s AND b.month = %s
    '''
    return db(query, (day, month)).all()

def upsert_chat(chat_id, title):
    query = '''
        INSERT INTO chats (chat_id, title, is_active)
        VALUES (%s, %s, TRUE)
        ON CONFLICT (chat_id)
        DO UPDATE SET title = EXCLUDED.title, is_active = TRUE
    '''
    db(query, (chat_id, title)).close()


def deactivate_chat(chat_id):
    db('UPDATE chats SET is_active = FALSE WHERE chat_id = %s', (chat_id,)).close()


def get_active_chats():
    query = 'SELECT chat_id, title FROM chats WHERE is_active = TRUE'
    return db(query).all()

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
        WHERE user_id = (SELECT id FROM users WHERE tg_id = %s)
          AND chat_id = %s
    '''
    db(query, (tg_id, chat_id)).close()


def get_chat_birthdays(chat_id):
    query = '''
        SELECT u.tg_id, u.tag, b.day, b.month, b.year
        FROM birthdays b
        JOIN users u ON u.id = b.user_id
        WHERE b.chat_id = %s
        ORDER BY b.month, b.day
    '''
    return db(query, (chat_id,)).all()

def get_or_create_character_id(name):
    row = db('SELECT id FROM character WHERE name = %s', (name,)).one()
    return row['id'] if row else None

def get_user_language(tg_id) -> str:
    row = db('SELECT language FROM users WHERE tg_id = %s', (tg_id,)).one()
    return row['language'] if row else 'RU'

def set_user_language(tg_id, language: str):
    db('UPDATE users SET language = %s WHERE tg_id = %s', (language, tg_id)).close()

def upsert_sheet_character(name, photo_url, affiliation, position):
    """
    Персонажи из таблицы матчатся по нормализованному имени.
    Если персонаж уже создан через бота (заявкой) — description и photo_file_id НЕ трогаем,
    обновляем только affiliation/position/photo_url и отмечаем активным.
    """
    existing = db(
        'SELECT id, source FROM character WHERE lower(name) = lower(%s)', (name,)
    ).one()

    if existing:
        query = '''
            UPDATE character
            SET affiliation = %s, position = %s, photo_url = %s,
                is_active = TRUE, updated_at = now()
            WHERE id = %s
        '''
        db(query, (affiliation, position, photo_url, existing['id'])).close()
        return existing['id']

    query = '''
        INSERT INTO character (name, affiliation, position, photo_url, source, is_active)
        VALUES (%s, %s, %s, %s, 'sheet', TRUE)
        RETURNING id
    '''
    row = db(query, (name, affiliation, position, photo_url)).one()
    return row['id']


def deactivate_missing_sheet_characters(current_names: list[str]) -> int:
    """Персонажей с source='sheet', которых больше нет в таблице, помечаем неактивными (не удаляем)."""
    if not current_names:
        placeholder_check = "TRUE"
        params = ()
    else:
        placeholder_check = "lower(name) NOT IN %s"
        params = (tuple(n.lower() for n in current_names),)

    query = f'''
        UPDATE character
        SET is_active = FALSE, updated_at = now()
        WHERE source = 'sheet' AND is_active = TRUE AND {placeholder_check}
        RETURNING id
    '''
    rows = db(query, params).all()
    return len(rows)


def get_user_by_username(username: str):
    return db('SELECT id, tg_id FROM users WHERE tag = %s', (username,)).one()


def link_user_character(user_id, character_id, assigned_by=None):
    query = '''
        INSERT INTO user_characters (user_id, character_id, assigned_by)
        VALUES (%s, %s, %s)
        ON CONFLICT (user_id, character_id) DO NOTHING
    '''
    db(query, (user_id, character_id, assigned_by)).close()


def unlink_user_character(user_id, character_id):
    db(
        'DELETE FROM user_characters WHERE user_id = %s AND character_id = %s',
        (user_id, character_id),
    ).close()


def get_user_characters(user_id):
    query = '''
        SELECT c.*
        FROM character c
        JOIN user_characters uc ON uc.character_id = c.id
        WHERE uc.user_id = %s AND c.is_active = TRUE
    '''
    return db(query, (user_id,)).all()


def add_pending_owner_link(username, character_id):
    query = '''
        INSERT INTO pending_owner_links (tg_username, character_id)
        VALUES (%s, %s)
        ON CONFLICT DO NOTHING
    '''
    db(query, (username, character_id)).close()


def resolve_pending_owner_links(username, user_id):
    """Вызывается при auth() — довязывает персонажей, если они ждали этого пользователя."""
    rows = db('SELECT character_id FROM pending_owner_links WHERE tg_username = %s', (username,)).all()
    for row in rows:
        link_user_character(user_id, row['character_id'])
    db('DELETE FROM pending_owner_links WHERE tg_username = %s', (username,)).close()

def get_character_by_id(character_id):
    return db('SELECT * FROM character WHERE id = %s', (character_id,)).one()

def create_character_request(user_id, chat_id, name, description, affiliation, position, photo_file_id):
    query = '''
        INSERT INTO character_requests (user_id, chat_id, name, description, affiliation, position, photo_file_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    '''
    row = db(query, (user_id, chat_id, name, description, affiliation, position, photo_file_id)).one()
    return row['id']


def get_request_by_id(request_id):
    return db('SELECT * FROM character_requests WHERE id = %s', (request_id,)).one()


def update_request_status(request_id, status):
    db(
        'UPDATE character_requests SET status = %s, resolved_at = now() WHERE id = %s',
        (status, request_id),
    ).close()


def update_request_field(request_id, field, value):
    allowed = {'name', 'description', 'affiliation', 'position'}
    if field not in allowed:
        raise ValueError(f'Недопустимое поле: {field}')
    db(f'UPDATE character_requests SET {field} = %s WHERE id = %s', (value, request_id)).close()


def get_user_requests(user_id):
    query = 'SELECT * FROM character_requests WHERE user_id = %s ORDER BY created_at DESC'
    return db(query, (user_id,)).all()


def create_bot_character(name, description, affiliation, position, photo_file_id):
    query = '''
        INSERT INTO character (name, description, affiliation, position, photo_file_id, source, is_active)
        VALUES (%s, %s, %s, %s, %s, 'bot', TRUE)
        RETURNING id
    '''
    row = db(query, (name, description, affiliation, position, photo_file_id)).one()
    return row['id']

def update_character_field(character_id, field, value):
    allowed = {'name', 'description', 'affiliation', 'position', 'photo_file_id'}
    if field not in allowed:
        raise ValueError(f'Недопустимое поле: {field}')
    db(f'UPDATE character SET {field} = %s, updated_at = now() WHERE id = %s', (value, character_id)).close()

def count_user_characters(user_id) -> int:
    row = db(
        'SELECT COUNT(*) AS cnt FROM user_characters uc '
        'JOIN character c ON c.id = uc.character_id '
        'WHERE uc.user_id = %s AND c.is_active = TRUE',
        (user_id,),
    ).one()
    return row['cnt']

def get_user_by_id(user_id):
    return db('SELECT * FROM users WHERE id = %s', (user_id,)).one()

def add_character_alias(character_id, alias):
    query = 'INSERT INTO character_aliases (character_id, alias) VALUES (%s, %s)'
    db(query, (character_id, alias)).close()

def get_all_aliases():
    query = '''
        SELECT ca.alias, c.name
        FROM character_aliases ca
        JOIN character c ON c.id = ca.character_id
        WHERE c.is_active = TRUE
    '''
    return db(query).all()