from database.queries import db


def get_public_stats():
    return db(
        '''
        SELECT
            (SELECT COUNT(*) FROM users WHERE left_at IS NULL) AS users,
            (SELECT COUNT(*) FROM character c JOIN users u ON u.id = c.owner_user_id WHERE u.left_at IS NULL) AS characters,
            (SELECT COUNT(*) FROM tag WHERE status = 'ACTIVE') AS tags,
            (SELECT COUNT(DISTINCT COALESCE(media_file_unique_id, media_file_id, media_url, id::text))
             FROM tag_usage
             WHERE is_public = TRUE AND (media_file_id IS NOT NULL OR media_url IS NOT NULL)) AS media
        '''
    ).one()


def list_active_tags():
    return db("SELECT id, name FROM tag WHERE status = 'ACTIVE' ORDER BY name").all()


def _media_filter(tag_id=None, kind=None, public_only=True, date_from=None, date_to=None):
    where = ['(tu.media_file_id IS NOT NULL OR tu.media_url IS NOT NULL)']
    params = []
    if public_only:
        where.extend(["tu.is_public = TRUE", "t.status = 'ACTIVE'"])
    if tag_id:
        where.append('tu.tag_id = %s')
        params.append(tag_id)
    if kind:
        if kind not in {'photo', 'video', 'video_link'}:
            raise ValueError('Неизвестный тип медиа')
        where.append('tu.media_type = %s')
        params.append(kind)
    if date_from:
        where.append('tu.used_at >= %s::date')
        params.append(date_from)
    if date_to:
        where.append('tu.used_at < %s::date + 1')
        params.append(date_to)
    return ' AND '.join(where), params


def list_media(
    tag_id=None, kind=None, sort='newest', limit=24, offset=0,
    public_only=True, date_from=None, date_to=None,
):
    where, params = _media_filter(tag_id, kind, public_only, date_from, date_to)
    order_by = {
        'newest': 'used_at DESC, id DESC',
        'oldest': 'used_at ASC, id ASC',
        'tag': 'tag_name ASC, used_at DESC',
    }.get(sort)
    if order_by is None:
        raise ValueError('Неизвестная сортировка')
    query = f'''
        SELECT * FROM (
            SELECT DISTINCT ON (COALESCE(tu.media_file_unique_id, tu.media_file_id, tu.media_url, tu.id::text))
                tu.id, tu.media_type, tu.media_file_id, tu.media_url, tu.caption,
                tu.used_at, tu.is_public, t.id AS tag_id, t.name AS tag_name
            FROM tag_usage tu
            JOIN tag t ON t.id = tu.tag_id
            WHERE {where}
            ORDER BY COALESCE(tu.media_file_unique_id, tu.media_file_id, tu.media_url, tu.id::text), tu.used_at DESC
        ) media
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    '''
    return db(query, (*params, limit, offset)).all()


def count_media(tag_id=None, kind=None, public_only=True, date_from=None, date_to=None):
    where, params = _media_filter(tag_id, kind, public_only, date_from, date_to)
    query = f'''
        SELECT COUNT(*) AS cnt FROM (
            SELECT DISTINCT COALESCE(tu.media_file_unique_id, tu.media_file_id, tu.media_url, tu.id::text)
            FROM tag_usage tu
            JOIN tag t ON t.id = tu.tag_id
            WHERE {where}
        ) media
    '''
    return db(query, tuple(params)).one()['cnt']


def get_public_media(usage_id):
    return db(
        '''
        SELECT tu.*, t.name AS tag_name
        FROM tag_usage tu
        JOIN tag t ON t.id = tu.tag_id
        WHERE tu.id = %s AND tu.is_public = TRUE AND t.status = 'ACTIVE'
        ''',
        (usage_id,),
    ).one()


def _user_search(search):
    where = 'u.left_at IS NULL'
    params = []
    if search and search.strip():
        where += ' AND u.tag ILIKE %s'
        params.append(f'%{search.strip()}%')
    return where, params


def list_users(limit=30, offset=0, search=None):
    where, params = _user_search(search)
    return db(
        f'''
        SELECT u.id, u.tag, fr.name AS role_name, uc.bio,
            c.id AS character_id, c.name AS character_name,
            (SELECT COUNT(*) FROM character WHERE owner_user_id = u.id) AS character_count,
            (SELECT COUNT(*) FROM subscription WHERE user_id = u.id AND active = TRUE) AS subscription_count
        FROM users u
        LEFT JOIN flavor_roles fr ON fr.id = u.flavor_role_id
        LEFT JOIN user_card uc ON uc.user_id = u.id
        LEFT JOIN character c ON c.owner_user_id = u.id AND c.is_primary = TRUE
        WHERE {where}
        ORDER BY u.tag NULLS LAST, u.id
        LIMIT %s OFFSET %s
        ''',
        (*params, limit, offset),
    ).all()


def count_users(search=None):
    where, params = _user_search(search)
    return db(f'SELECT COUNT(*) AS cnt FROM users u WHERE {where}', tuple(params)).one()['cnt']


def get_public_user(user_id):
    return db(
        '''
        SELECT u.id, u.tag, fr.name AS role_name, fr.description AS role_description,
            fr.wiki_url AS role_wiki_url, uc.bio,
            (SELECT COUNT(*) FROM character WHERE owner_user_id = u.id) AS character_count,
            (SELECT COUNT(*) FROM subscription WHERE user_id = u.id AND active = TRUE) AS subscription_count
        FROM users u
        LEFT JOIN flavor_roles fr ON fr.id = u.flavor_role_id
        LEFT JOIN user_card uc ON uc.user_id = u.id
        WHERE u.id = %s AND u.left_at IS NULL
        ''',
        (user_id,),
    ).one()


def get_user_avatar_data(user_id):
    return db(
        'SELECT tg_id, avatar_file_id, avatar_updated_at FROM users WHERE id = %s AND left_at IS NULL',
        (user_id,),
    ).one()


def update_user_avatar(user_id, file_id):
    db(
        'UPDATE users SET avatar_file_id = %s, avatar_updated_at = now() WHERE id = %s',
        (file_id, user_id),
    ).close()


def get_public_user_games(user_id):
    return db(
        '''
        SELECT g.name FROM user_games ug JOIN games g ON g.code = ug.game_code
        WHERE ug.user_id = %s ORDER BY g.name
        ''',
        (user_id,),
    ).all()


def get_public_user_characters(user_id):
    return db(
        '''
        SELECT c.id, c.name, c.description, c.photo_file_id, c.is_primary,
            c.birth_date, p.name AS position_name, a.name AS affiliation_name
        FROM character c
        LEFT JOIN positions p ON p.id = c.position_id
        LEFT JOIN affiliations a ON a.id = c.affiliation_id
        WHERE c.owner_user_id = %s
        ORDER BY c.is_primary DESC, c.name
        ''',
        (user_id,),
    ).all()


def list_characters(limit=30, offset=0):
    return db(
        '''
        SELECT c.id, c.name, c.description, c.photo_file_id, c.is_primary,
            c.birth_date, u.id AS owner_id, u.tag AS owner_tag,
            p.name AS position_name, a.name AS affiliation_name
        FROM character c
        JOIN users u ON u.id = c.owner_user_id AND u.left_at IS NULL
        LEFT JOIN positions p ON p.id = c.position_id
        LEFT JOIN affiliations a ON a.id = c.affiliation_id
        ORDER BY c.is_primary DESC, c.name
        LIMIT %s OFFSET %s
        ''',
        (limit, offset),
    ).all()


def count_characters():
    return db(
        '''
        SELECT COUNT(*) AS cnt FROM character c
        JOIN users u ON u.id = c.owner_user_id WHERE u.left_at IS NULL
        '''
    ).one()['cnt']


def get_public_character(character_id):
    return db(
        '''
        SELECT c.*, u.id AS owner_id, u.tag AS owner_tag, uc.bio AS owner_bio,
            p.name AS position_name, a.name AS affiliation_name
        FROM character c
        JOIN users u ON u.id = c.owner_user_id AND u.left_at IS NULL
        LEFT JOIN user_card uc ON uc.user_id = u.id
        LEFT JOIN positions p ON p.id = c.position_id
        LEFT JOIN affiliations a ON a.id = c.affiliation_id
        WHERE c.id = %s
        ''',
        (character_id,),
    ).one()


def get_admin_overview():
    return db(
        '''
        SELECT
            (SELECT COUNT(*) FROM users WHERE left_at IS NULL) AS users,
            (SELECT COUNT(*) FROM character) AS characters,
            (SELECT COUNT(*) FROM flavor_roles) AS roles,
            (SELECT COUNT(*) FROM tag WHERE status = 'ACTIVE') AS tags
        '''
    ).one()


def list_admin_users():
    return db('SELECT id, tag FROM users WHERE left_at IS NULL ORDER BY tag NULLS LAST, id').all()


def list_admin_characters():
    return db(
        '''
        SELECT c.id, c.name, c.is_primary, c.description, c.birth_date,
            u.id AS owner_id, u.tag AS owner_tag
        FROM character c JOIN users u ON u.id = c.owner_user_id
        ORDER BY c.name
        '''
    ).all()


def list_admin_roles():
    return db(
        '''
        SELECT fr.*, COUNT(u.id) AS user_count
        FROM flavor_roles fr LEFT JOIN users u ON u.flavor_role_id = fr.id
        GROUP BY fr.id ORDER BY fr.name
        '''
    ).all()


def list_admin_media(limit=50):
    return list_media(limit=limit, public_only=False)


def _audit(tx, admin_tg_id, action, entity_type, entity_id, details=None):
    import json

    tx(
        '''
        INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id, details)
        VALUES (%s, %s, %s, %s, %s::jsonb)
        ''',
        (admin_tg_id, action, entity_type, str(entity_id), json.dumps(details or {}, ensure_ascii=False)),
    ).close()


def create_role(admin_tg_id, name, description=None, wiki_url=None):
    with db.transaction() as tx:
        row = tx(
            '''
            INSERT INTO flavor_roles (name, description, wiki_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (name) DO NOTHING RETURNING id
            ''',
            (name, description, wiki_url),
        ).one()
        if not row:
            raise ValueError('Роль с таким названием уже существует')
        _audit(tx, admin_tg_id, 'create', 'flavor_role', row['id'], {'name': name})
        return row['id']


def create_character(admin_tg_id, owner_user_id, name, birth_date=None, description=None, is_primary=False):
    with db.transaction() as tx:
        if not tx('SELECT 1 FROM users WHERE id = %s FOR UPDATE', (owner_user_id,)).one():
            raise ValueError('Игрок не найден')
        if tx('SELECT 1 FROM character WHERE lower(name) = lower(%s)', (name,)).one():
            raise ValueError('Персонаж с таким именем уже существует')
        count = tx(
            'SELECT COUNT(*) AS cnt FROM character WHERE owner_user_id = %s',
            (owner_user_id,),
        ).one()['cnt']
        if count >= 3:
            raise ValueError('У игрока уже максимальное количество персонажей: 3')
        primary = is_primary or count == 0
        if primary:
            tx('UPDATE character SET is_primary = FALSE WHERE owner_user_id = %s', (owner_user_id,)).close()
        row = tx(
            '''
            INSERT INTO character (owner_user_id, name, birth_date, description, is_primary)
            VALUES (%s, %s, %s, %s, %s) RETURNING id
            ''',
            (owner_user_id, name, birth_date, description, primary),
        ).one()
        _audit(tx, admin_tg_id, 'create', 'character', row['id'], {'owner_user_id': owner_user_id, 'name': name})
        return row['id']


def assign_character(admin_tg_id, character_id, owner_user_id, is_primary=False):
    with db.transaction() as tx:
        character = tx('SELECT * FROM character WHERE id = %s FOR UPDATE', (character_id,)).one()
        if not character:
            raise ValueError('Персонаж не найден')
        if not tx('SELECT 1 FROM users WHERE id = %s FOR UPDATE', (owner_user_id,)).one():
            raise ValueError('Игрок не найден')
        if character['owner_user_id'] != owner_user_id:
            count = tx(
                'SELECT COUNT(*) AS cnt FROM character WHERE owner_user_id = %s',
                (owner_user_id,),
            ).one()['cnt']
            if count >= 3:
                raise ValueError('У игрока уже максимальное количество персонажей: 3')
        if is_primary:
            tx('UPDATE character SET is_primary = FALSE WHERE owner_user_id = %s', (owner_user_id,)).close()
        tx(
            'UPDATE character SET owner_user_id = %s, is_primary = %s WHERE id = %s',
            (owner_user_id, is_primary, character_id),
        ).close()
        _audit(tx, admin_tg_id, 'assign', 'character', character_id, {
            'from_user_id': character['owner_user_id'], 'to_user_id': owner_user_id,
        })


def set_media_visibility(admin_tg_id, usage_id, is_public):
    with db.transaction() as tx:
        item = tx('SELECT * FROM tag_usage WHERE id = %s FOR UPDATE', (usage_id,)).one()
        if not item:
            raise ValueError('Публикация не найдена')
        if item['media_file_unique_id']:
            tx(
                'UPDATE tag_usage SET is_public = %s WHERE media_file_unique_id = %s',
                (is_public, item['media_file_unique_id']),
            ).close()
        elif item['media_file_id']:
            tx(
                'UPDATE tag_usage SET is_public = %s WHERE media_file_id = %s',
                (is_public, item['media_file_id']),
            ).close()
        elif item['media_url']:
            tx(
                'UPDATE tag_usage SET is_public = %s WHERE media_url = %s',
                (is_public, item['media_url']),
            ).close()
        else:
            tx('UPDATE tag_usage SET is_public = %s WHERE id = %s', (is_public, usage_id)).close()
        _audit(tx, admin_tg_id, 'show' if is_public else 'hide', 'tag_usage', usage_id)


def get_daily_analytics(day):
    return db(
        '''
        SELECT COUNT(*) AS total,
            COUNT(*) FILTER (WHERE media_type = 'photo') AS photo,
            COUNT(*) FILTER (WHERE media_type = 'video') AS video,
            COUNT(*) FILTER (WHERE media_type = 'video_link') AS video_link
        FROM tag_usage
        WHERE used_at >= %s::date AND used_at < %s::date + 1
        ''',
        (day, day),
    ).one()


def get_tag_popularity_for_day(day, rare=False, limit=10):
    direction = 'ASC' if rare else 'DESC'
    return db(
        f'''
        SELECT t.id, t.name, COUNT(tu.id) AS cnt
        FROM tag_usage tu JOIN tag t ON t.id = tu.tag_id
        WHERE tu.used_at >= %s::date AND tu.used_at < %s::date + 1
        GROUP BY t.id, t.name
        ORDER BY cnt {direction}, t.name
        LIMIT %s
        ''',
        (day, day, limit),
    ).all()


def get_tag_daily_series(days=14):
    return db(
        '''
        SELECT d.day::date AS day, COUNT(tu.id) AS total,
            COUNT(tu.id) FILTER (WHERE tu.media_type = 'photo') AS photo,
            COUNT(tu.id) FILTER (WHERE tu.media_type = 'video') AS video,
            COUNT(tu.id) FILTER (WHERE tu.media_type = 'video_link') AS video_link
        FROM generate_series(CURRENT_DATE - (%s - 1) * INTERVAL '1 day', CURRENT_DATE, INTERVAL '1 day') d(day)
        LEFT JOIN tag_usage tu ON tu.used_at >= d.day AND tu.used_at < d.day + INTERVAL '1 day'
        GROUP BY d.day ORDER BY d.day
        ''',
        (days,),
    ).all()


def get_recent_audit(limit=10):
    return db('SELECT * FROM admin_audit_log ORDER BY created_at DESC LIMIT %s', (limit,)).all()
