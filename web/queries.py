from database.queries import db, get_character_tags
from services.validation import is_valid_tag_name


class ConcurrentEditError(ValueError):
    pass


_UNSET = object()


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
    return db(
        '''
        SELECT id, name FROM tag
        WHERE status = 'ACTIVE'
        ORDER BY EXISTS (
            SELECT 1 FROM tag_usage tu
            WHERE tu.tag_id = tag.id AND tu.is_public = TRUE
                AND (tu.media_file_id IS NOT NULL OR tu.media_url IS NOT NULL)
        ) DESC, CASE
            WHEN name ~ '^[A-Za-z]' THEN 0
            WHEN name ~ '^[А-Яа-яЁё]' THEN 1
            ELSE 2
        END, lower(name)
        '''
    ).all()


def search_active_tags(prefix):
    if not prefix:
        return list_active_tags()
    escaped_prefix = prefix.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return db(
        '''
        SELECT id, name FROM tag
        WHERE status = 'ACTIVE' AND lower(name) LIKE lower(%s) || '%%' ESCAPE '\\'
        ORDER BY EXISTS (
            SELECT 1 FROM tag_usage tu
            WHERE tu.tag_id = tag.id AND tu.is_public = TRUE
                AND (tu.media_file_id IS NOT NULL OR tu.media_url IS NOT NULL)
        ) DESC, CASE
            WHEN name ~ '^[A-Za-z]' THEN 0
            WHEN name ~ '^[А-Яа-яЁё]' THEN 1
            ELSE 2
        END, lower(name)
        ''',
        (escaped_prefix,),
    ).all()


def _media_filter(tag_ids=None, kinds=None, public_only=True, date_from=None, date_to=None):
    where = ['(tu.media_file_id IS NOT NULL OR tu.media_url IS NOT NULL)']
    params = []
    if public_only:
        where.extend(["tu.is_public = TRUE", "t.status = 'ACTIVE'"])
    if tag_ids:
        where.append('tu.tag_id = ANY(%s)')
        params.append(list(tag_ids))
    if kinds:
        if any(kind not in {'photo', 'video', 'video_link'} for kind in kinds):
            raise ValueError('Неизвестный тип медиа')
        where.append('tu.media_type = ANY(%s)')
        params.append(list(kinds))
    if date_from:
        where.append('tu.used_at >= %s::date')
        params.append(date_from)
    if date_to:
        where.append('tu.used_at < %s::date + 1')
        params.append(date_to)
    return ' AND '.join(where), params


def list_media(
    tag_ids=None, kinds=None, sort=None, limit=24, offset=0,
    public_only=True, date_from=None, date_to=None,
):
    where, params = _media_filter(tag_ids, kinds, public_only, date_from, date_to)
    sort_keys = [sort] if isinstance(sort, str) else list(sort or ['newest'])
    if not sort_keys:
        sort_keys = ['newest']
    order_parts = []
    for sort_key in sort_keys:
        order_by = {
            'newest': 'used_at DESC, id DESC',
            'oldest': 'used_at ASC, id ASC',
            'tag': 'tag_name ASC, used_at DESC',
        }.get(sort_key)
        if order_by is None:
            raise ValueError('Неизвестная сортировка')
        order_parts.append(order_by)
    order_by = ', '.join(order_parts)
    tag_visibility = "tu2.is_public = TRUE AND t2.status = 'ACTIVE'" if public_only else 'TRUE'
    query = f'''
        SELECT media.*, u.id AS author_id, u.tag AS author_tag,
            COALESCE((
                SELECT json_agg(tag_item ORDER BY tag_item.name)
                FROM (
                    SELECT DISTINCT t2.id, t2.name
                    FROM tag_usage tu2
                    JOIN tag t2 ON t2.id = tu2.tag_id
                    WHERE COALESCE(tu2.media_file_unique_id, tu2.media_file_id, tu2.media_url, tu2.id::text) = media.media_key
                        AND {tag_visibility}
                ) tag_item
            ), json_build_array(json_build_object('id', media.tag_id, 'name', media.tag_name))) AS tag_items
        FROM (
            SELECT DISTINCT ON (COALESCE(tu.media_file_unique_id, tu.media_file_id, tu.media_url, tu.id::text))
                tu.id, tu.media_type, tu.media_file_id, tu.media_file_unique_id, tu.media_url,
                tu.caption, tu.used_at, tu.is_public, tu.author_tg_id,
                t.id AS tag_id, t.name AS tag_name,
                COALESCE(tu.media_file_unique_id, tu.media_file_id, tu.media_url, tu.id::text) AS media_key
            FROM tag_usage tu
            JOIN tag t ON t.id = tu.tag_id
            WHERE {where}
            ORDER BY COALESCE(tu.media_file_unique_id, tu.media_file_id, tu.media_url, tu.id::text), tu.used_at DESC
        ) media
        LEFT JOIN users u ON u.tg_id = media.author_tg_id
        ORDER BY {order_by}
        LIMIT %s OFFSET %s
    '''
    return db(query, (*params, limit, offset)).all()


def count_media(tag_ids=None, kinds=None, public_only=True, date_from=None, date_to=None):
    where, params = _media_filter(tag_ids, kinds, public_only, date_from, date_to)
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
        SELECT u.id, u.tag, u.chat_position, uc.bio,
            c.id AS character_id, c.name AS character_name,
            (SELECT COUNT(*) FROM character WHERE owner_user_id = u.id) AS character_count,
            (SELECT COUNT(*) FROM subscription WHERE user_id = u.id AND active = TRUE) AS subscription_count
        FROM users u
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
        SELECT u.id, u.tag, u.chat_position, uc.bio,
            b.day AS birth_day, b.month AS birth_month, b.year AS birth_year,
            (SELECT COUNT(*) FROM character WHERE owner_user_id = u.id) AS character_count,
            (SELECT COUNT(*) FROM subscription WHERE user_id = u.id AND active = TRUE) AS subscription_count
        FROM users u
        LEFT JOIN user_card uc ON uc.user_id = u.id
        LEFT JOIN birthdays b ON b.user_id = u.id
        WHERE u.id = %s AND u.left_at IS NULL
        ''',
        (user_id,),
    ).one()


def get_public_user_subscriptions(user_id):
    return db(
        '''
        SELECT t.id, t.name
        FROM subscription s
        JOIN tag t ON t.id = s.tag_id
        WHERE s.user_id = %s AND s.active = TRUE
        ORDER BY t.name
        ''',
        (user_id,),
    ).all()


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
            c.birth_date, p.name AS position_name, (SELECT STRING_AGG(DISTINCT aff.name, ', ' ORDER BY aff.name)
             FROM affiliations aff
             WHERE aff.id = c.affiliation_id OR EXISTS (
                 SELECT 1 FROM character_affiliation ca
                 WHERE ca.character_id = c.id AND ca.affiliation_id = aff.id
             )) AS affiliation_name
        FROM character c
        LEFT JOIN positions p ON p.id = c.position_id
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
            p.name AS position_name, (SELECT STRING_AGG(DISTINCT aff.name, ', ' ORDER BY aff.name)
             FROM affiliations aff
             WHERE aff.id = c.affiliation_id OR EXISTS (
                 SELECT 1 FROM character_affiliation ca
                 WHERE ca.character_id = c.id AND ca.affiliation_id = aff.id
             )) AS affiliation_name
        FROM character c
        JOIN users u ON u.id = c.owner_user_id AND u.left_at IS NULL
        LEFT JOIN positions p ON p.id = c.position_id
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
        SELECT c.*, u.id AS owner_id, u.tag AS owner_tag,
            p.name AS position_name, (SELECT STRING_AGG(DISTINCT aff.name, ', ' ORDER BY aff.name)
             FROM affiliations aff
             WHERE aff.id = c.affiliation_id OR EXISTS (
                 SELECT 1 FROM character_affiliation ca
                 WHERE ca.character_id = c.id AND ca.affiliation_id = aff.id
             )) AS affiliation_name
        FROM character c
        JOIN users u ON u.id = c.owner_user_id AND u.left_at IS NULL
        LEFT JOIN positions p ON p.id = c.position_id
        WHERE c.id = %s
        ''',
        (character_id,),
    ).one()


def get_public_character_tags(character_id):
    return get_character_tags(character_id)


def get_admin_overview():
    return db(
        '''
        SELECT
            (SELECT COUNT(*) FROM users WHERE left_at IS NULL) AS users,
            (SELECT COUNT(*) FROM character) AS characters,
            (SELECT COUNT(*) FROM tag WHERE status = 'ACTIVE') AS tags
        '''
    ).one()


def list_admin_users():
    return db('SELECT id, tag FROM users WHERE left_at IS NULL ORDER BY tag NULLS LAST, id').all()


def list_admin_tags(search='', status=''):
    where = ['TRUE']
    params = []
    if search.strip():
        where.append(
            '''(t.name ILIKE %s OR EXISTS (
                SELECT 1 FROM tag_alias search_alias
                WHERE search_alias.tag_id = t.id AND search_alias.alias ILIKE %s
            ))'''
        )
        pattern = f'{search.strip()}%'
        params.extend((pattern, pattern))
    if status:
        if status not in {'ACTIVE', 'DELETED', 'BLOCKED'}:
            raise ValueError('Неизвестный статус тега')
        where.append('t.status = %s')
        params.append(status)
    return db(
        f'''
        SELECT t.id, t.name, t.status,
            COALESCE(
                json_agg(json_build_object('id', ta.id, 'alias', ta.alias) ORDER BY ta.alias)
                    FILTER (WHERE ta.id IS NOT NULL),
                '[]'
            ) AS aliases,
            (SELECT COUNT(*) FROM tag_usage tu WHERE tu.tag_id = t.id) AS usages,
            (SELECT COUNT(*) FROM subscription s WHERE s.tag_id = t.id AND s.active = TRUE) AS subscriptions
        FROM tag t
        LEFT JOIN tag_alias ta ON ta.tag_id = t.id
        WHERE {' AND '.join(where)}
        GROUP BY t.id
        ORDER BY CASE t.status WHEN 'ACTIVE' THEN 0 ELSE 1 END, lower(t.name)
        ''',
        tuple(params),
    ).all()


def list_admin_character_tag_links(search=''):
    rows = db(
        '''
        SELECT c.id, c.name, u.tag AS owner_tag,
            (SELECT STRING_AGG(DISTINCT linked.name, ', ' ORDER BY linked.name)
             FROM tag linked
             LEFT JOIN tag_alias ta ON ta.tag_id = linked.id
             WHERE linked.status = 'ACTIVE'
                 AND (lower(linked.name) = lower(c.name) OR lower(ta.alias) = lower(c.name))
            ) AS tag_names
        FROM character c
        JOIN users u ON u.id = c.owner_user_id
        ORDER BY lower(c.name)
        '''
    ).all()
    needle = search.strip().casefold()
    if not needle:
        return rows
    return [
        row for row in rows
        if row['name'].casefold().startswith(needle)
        or (row['owner_tag'] or '').casefold().startswith(needle)
        or any(
            tag.strip().casefold().startswith(needle)
            for tag in (row['tag_names'] or '').split(',') if tag.strip()
        )
    ]


def get_admin_tag(tag_id):
    return db(
        '''
        SELECT t.id, t.name, t.status,
            COALESCE(
                json_agg(json_build_object('id', ta.id, 'alias', ta.alias) ORDER BY ta.alias)
                    FILTER (WHERE ta.id IS NOT NULL),
                '[]'
            ) AS aliases,
            (SELECT COUNT(*) FROM tag_usage tu WHERE tu.tag_id = t.id) AS usages,
            (SELECT COUNT(*) FROM subscription s WHERE s.tag_id = t.id AND s.active = TRUE) AS subscriptions
        FROM tag t
        LEFT JOIN tag_alias ta ON ta.tag_id = t.id
        WHERE t.id = %s
        GROUP BY t.id
        ''',
        (tag_id,),
    ).one()


def get_admin_tag_character_links(tag_id):
    return db(
        '''
        SELECT c.id, c.name, u.tag AS owner_tag, ta.id AS alias_id,
            CASE WHEN lower(t.name) = lower(c.name) THEN 'tag' ELSE 'alias' END AS link_type
        FROM tag t
        JOIN character c ON lower(t.name) = lower(c.name) OR EXISTS (
            SELECT 1 FROM tag_alias linked_alias
            WHERE linked_alias.tag_id = t.id AND lower(linked_alias.alias) = lower(c.name)
        )
        LEFT JOIN tag_alias ta ON ta.tag_id = t.id AND lower(ta.alias) = lower(c.name)
        JOIN users u ON u.id = c.owner_user_id
        WHERE t.id = %s
        ORDER BY lower(c.name)
        ''',
        (tag_id,),
    ).all()


def update_admin_tag_status(admin_tg_id, tag_id, status):
    if status not in {'ACTIVE', 'DELETED', 'BLOCKED'}:
        raise ValueError('Неизвестный статус тега')
    with db.transaction() as tx:
        tag = tx('SELECT id, name, status FROM tag WHERE id = %s FOR UPDATE', (tag_id,)).one()
        if not tag:
            raise ValueError('Тег не найден')
        tx('UPDATE tag SET status = %s WHERE id = %s', (status, tag_id)).close()
        _audit(tx, admin_tg_id, 'update', 'tag', tag_id, {
            'name': tag['name'], 'from_status': tag['status'], 'to_status': status,
        })


def delete_admin_tag(admin_tg_id, tag_id):
    with db.transaction() as tx:
        tag = tx('SELECT id, name FROM tag WHERE id = %s FOR UPDATE', (tag_id,)).one()
        if not tag:
            raise ValueError('Тег не найден')
        usage_count = tx('SELECT COUNT(*) AS cnt FROM tag_usage WHERE tag_id = %s', (tag_id,)).one()['cnt']
        tx('DELETE FROM tag WHERE id = %s', (tag_id,)).close()
        _audit(tx, admin_tg_id, 'delete', 'tag', tag_id, {
            'name': tag['name'], 'tag_usage_count': usage_count,
        })


def add_admin_tag_alias(admin_tg_id, tag_id, alias, character_id=None):
    with db.transaction() as tx:
        tag = tx('SELECT id, name, status FROM tag WHERE id = %s FOR UPDATE', (tag_id,)).one()
        if not tag or tag['status'] != 'ACTIVE':
            raise ValueError('Основной тег не найден или неактивен')
        if character_id is not None:
            character = tx('SELECT id, name FROM character WHERE id = %s', (character_id,)).one()
            if not character:
                raise ValueError('Персонаж не найден')
            alias = character['name']
        alias = alias.strip()
        if not alias:
            raise ValueError('Введите алиас')
        if not is_valid_tag_name(alias):
            raise ValueError('Алиас может содержать только буквы, цифры, дефис и подчёркивание, без пробелов')
        collision = tx(
            '''
            SELECT 'tag' AS source, id, name, status, name AS matched_name
            FROM tag WHERE lower(replace(name, 'ё', 'е')) = lower(replace(%s, 'ё', 'е'))
            UNION ALL
            SELECT 'alias' AS source, t.id, t.name, t.status, ta.alias AS matched_name
            FROM tag_alias ta JOIN tag t ON t.id = ta.tag_id
            WHERE lower(replace(ta.alias, 'ё', 'е')) = lower(replace(%s, 'ё', 'е'))
            LIMIT 1
            ''',
            (alias, alias),
        ).one()
        if collision:
            if collision['source'] == 'alias' and collision['id'] == tag_id:
                raise ValueError(f'Алиас «{alias}» уже привязан к основному тегу «{collision["name"]}»')
            character = tx('SELECT id, name FROM character WHERE lower(name) = lower(%s)', (alias,)).one()
            if collision['source'] == 'alias':
                relation = f'алиасом «{collision["matched_name"]}» основного тега «{collision["name"]}»'
                if character:
                    relation += f' (привязка персонажа «{character["name"]}»)'
            else:
                relation = f'основным тегом «{collision["name"]}»'
                if character:
                    relation += f'; у персонажа «{character["name"]}» уже есть одноимённый тег'
            raise ValueError(f'Имя «{alias}» уже используется: {relation}')
        row = tx(
            'INSERT INTO tag_alias (tag_id, alias) VALUES (%s, %s) RETURNING id',
            (tag_id, alias),
        ).one()
        _audit(tx, admin_tg_id, 'create', 'tag_alias', row['id'], {
            'tag_id': tag_id, 'alias': alias, 'character_id': character_id,
        })
        return row


def delete_admin_tag_alias(admin_tg_id, alias_id):
    with db.transaction() as tx:
        row = tx(
            'DELETE FROM tag_alias WHERE id = %s RETURNING id, tag_id, alias',
            (alias_id,),
        ).one()
        if not row:
            raise ValueError('Алиас не найден')
        _audit(tx, admin_tg_id, 'delete', 'tag_alias', alias_id, {
            'tag_id': row['tag_id'], 'alias': row['alias'],
        })


def list_admin_affiliations(search=''):
    where = 'TRUE'
    params = ()
    if search.strip():
        where = 'a.name ILIKE %s'
        params = (f'{search.strip()}%',)
    return db(
        f'''
        SELECT a.id, a.name, a.parent_id, parent.name AS parent_name,
            (SELECT COUNT(*) FROM character_affiliation ca WHERE ca.affiliation_id = a.id)
            + (SELECT COUNT(*) FROM character c
               WHERE c.affiliation_id = a.id AND NOT EXISTS (
                   SELECT 1 FROM character_affiliation ca
                   WHERE ca.character_id = c.id AND ca.affiliation_id = a.id
               )) AS character_count
        FROM affiliations a
        LEFT JOIN affiliations parent ON parent.id = a.parent_id
        WHERE {where}
        ORDER BY parent.name NULLS FIRST, a.name
        ''',
        params,
    ).all()


def get_admin_affiliation(affiliation_id):
    return db(
        '''
        SELECT a.id, a.name, a.parent_id, parent.name AS parent_name
        FROM affiliations a LEFT JOIN affiliations parent ON parent.id = a.parent_id
        WHERE a.id = %s
        ''',
        (affiliation_id,),
    ).one()


def list_admin_character_affiliations(search=''):
    rows = db(
        '''
        SELECT c.id, c.name, u.tag AS owner_tag,
            (SELECT STRING_AGG(DISTINCT aff.name, ', ' ORDER BY aff.name)
             FROM affiliations aff
             WHERE aff.id = c.affiliation_id OR EXISTS (
                 SELECT 1 FROM character_affiliation ca
                 WHERE ca.character_id = c.id AND ca.affiliation_id = aff.id
             )) AS affiliation_names,
            COALESCE((SELECT json_agg(json_build_object('id', aff.id, 'name', aff.name) ORDER BY aff.name)
             FROM affiliations aff
             WHERE EXISTS (
                 SELECT 1 FROM character_affiliation ca
                 WHERE ca.character_id = c.id AND ca.affiliation_id = aff.id
             )), '[]') AS memberships
        FROM character c JOIN users u ON u.id = c.owner_user_id
        ORDER BY lower(c.name)
        '''
    ).all()
    needle = search.strip().casefold()
    if not needle:
        return rows
    return [
        row for row in rows
        if row['name'].casefold().startswith(needle)
        or (row['owner_tag'] or '').casefold().startswith(needle)
        or any(
            name.strip().casefold().startswith(needle)
            for name in (row['affiliation_names'] or '').split(',') if name.strip()
        )
    ]


def get_admin_character_affiliation_ids(character_id):
    return {
        row['affiliation_id']
        for row in db(
            'SELECT affiliation_id FROM character_affiliation WHERE character_id = %s',
            (character_id,),
        ).all()
    }


def _validate_affiliation_parent(tx, parent_id, affiliation_id=None):
    if parent_id is None:
        return
    if not tx('SELECT id FROM affiliations WHERE id = %s', (parent_id,)).one():
        raise ValueError('Родительская принадлежность не найдена')
    if affiliation_id is None:
        return
    if parent_id == affiliation_id:
        raise ValueError('Принадлежность не может быть родителем самой себя')
    descendant = tx(
        '''
        WITH RECURSIVE descendants AS (
            SELECT id FROM affiliations WHERE id = %s
            UNION ALL
            SELECT a.id FROM affiliations a
            JOIN descendants d ON a.parent_id = d.id
        )
        SELECT id FROM descendants WHERE id = %s
        ''',
        (affiliation_id, parent_id),
    ).one()
    if descendant:
        raise ValueError('Нельзя назначить родителем дочернюю принадлежность')


def _check_affiliation_name_free(tx, name, parent_id, exclude_id=None):
    duplicate = tx(
        '''
        SELECT id FROM affiliations
        WHERE lower(name) = lower(%s)
            AND ((parent_id IS NULL AND %s IS NULL) OR parent_id = %s)
            AND (%s IS NULL OR id <> %s)
        ''',
        (name, parent_id, parent_id, exclude_id, exclude_id),
    ).one()
    if duplicate:
        raise ValueError('Принадлежность с таким именем уже существует на этом уровне')


def create_admin_affiliation(admin_tg_id, name, parent_id=None):
    with db.transaction() as tx:
        _validate_affiliation_parent(tx, parent_id)
        _check_affiliation_name_free(tx, name, parent_id)
        row = tx(
            'INSERT INTO affiliations (name, parent_id) VALUES (%s, %s) RETURNING id',
            (name, parent_id),
        ).one()
        _audit(tx, admin_tg_id, 'create', 'affiliation', row['id'], {
            'name': name, 'parent_id': parent_id,
        })
        return row


def update_admin_affiliation(admin_tg_id, affiliation_id, name, parent_id=None):
    with db.transaction() as tx:
        current = tx('SELECT id, name, parent_id FROM affiliations WHERE id = %s', (affiliation_id,)).one()
        if not current:
            raise ValueError('Принадлежность не найдена')
        _validate_affiliation_parent(tx, parent_id, affiliation_id)
        _check_affiliation_name_free(tx, name, parent_id, affiliation_id)
        tx(
            'UPDATE affiliations SET name = %s, parent_id = %s WHERE id = %s',
            (name, parent_id, affiliation_id),
        ).close()
        _audit(tx, admin_tg_id, 'update', 'affiliation', affiliation_id, {
            'from': dict(current), 'to': {'name': name, 'parent_id': parent_id},
        })


def delete_admin_affiliation(admin_tg_id, affiliation_id):
    with db.transaction() as tx:
        row = tx(
            'DELETE FROM affiliations WHERE id = %s RETURNING id, name, parent_id',
            (affiliation_id,),
        ).one()
        if not row:
            raise ValueError('Принадлежность не найдена')
        _audit(tx, admin_tg_id, 'delete', 'affiliation', affiliation_id, {
            'name': row['name'], 'parent_id': row['parent_id'],
        })


def add_admin_character_affiliation(admin_tg_id, character_id, affiliation_id):
    with db.transaction() as tx:
        if not tx('SELECT id FROM character WHERE id = %s', (character_id,)).one():
            raise ValueError('Персонаж не найден')
        if not tx('SELECT id FROM affiliations WHERE id = %s', (affiliation_id,)).one():
            raise ValueError('Принадлежность не найдена')
        row = tx(
            '''
            INSERT INTO character_affiliation (character_id, affiliation_id)
            VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING affiliation_id
            ''',
            (character_id, affiliation_id),
        ).one()
        if not row:
            raise ValueError('Эта принадлежность уже назначена персонажу')
        _audit(tx, admin_tg_id, 'assign', 'character_affiliation', character_id, {
            'affiliation_id': affiliation_id,
        })


def remove_admin_character_affiliation(admin_tg_id, character_id, affiliation_id):
    with db.transaction() as tx:
        row = tx(
            '''
            DELETE FROM character_affiliation
            WHERE character_id = %s AND affiliation_id = %s
            RETURNING affiliation_id
            ''',
            (character_id, affiliation_id),
        ).one()
        if not row:
            raise ValueError('Такой привязки у персонажа нет')
        _audit(tx, admin_tg_id, 'unassign', 'character_affiliation', character_id, {
            'affiliation_id': affiliation_id,
        })


def list_admin_players():
    return db(
        '''
        SELECT u.id, u.tag, u.chat_position, uc.bio, b.day, b.month, b.year,
            (SELECT STRING_AGG(title.name, ', ' ORDER BY lower(title.name))
             FROM user_titles title WHERE title.user_id = u.id) AS titles,
            (SELECT STRING_AGG(g.name, ', ' ORDER BY g.name)
             FROM user_games ug JOIN games g ON g.code = ug.game_code
             WHERE ug.user_id = u.id) AS game_names
        FROM users u
        LEFT JOIN user_card uc ON uc.user_id = u.id
        LEFT JOIN birthdays b ON b.user_id = u.id
        WHERE u.left_at IS NULL
        ORDER BY u.tag NULLS LAST, u.id
        '''
    ).all()


def get_admin_player(user_id):
    return db(
        '''
        SELECT u.id, u.tag, u.chat_position, u.lock_version, uc.bio, b.day, b.month, b.year,
            COALESCE((SELECT array_agg(ug.game_code ORDER BY ug.game_code)
                      FROM user_games ug WHERE ug.user_id = u.id), ARRAY[]::text[]) AS game_codes
        FROM users u
        LEFT JOIN user_card uc ON uc.user_id = u.id
        LEFT JOIN birthdays b ON b.user_id = u.id
        WHERE u.id = %s AND u.left_at IS NULL
        ''',
        (user_id,),
    ).one()


def list_games():
    return db('SELECT code, name FROM games ORDER BY name').all()


def list_admin_games():
    return db(
        '''
        SELECT g.code, g.name, COUNT(ug.user_id) AS user_count
        FROM games g
        LEFT JOIN user_games ug ON ug.game_code = g.code
        GROUP BY g.code, g.name
        ORDER BY g.name
        '''
    ).all()


def create_admin_game(admin_tg_id, name, code):
    with db.transaction() as tx:
        if tx('SELECT 1 FROM games WHERE lower(name) = lower(%s)', (name,)).one():
            raise ValueError('Игра с таким названием уже существует')
        base_code = code
        suffix = 2
        while tx('SELECT 1 FROM games WHERE code = %s', (code,)).one():
            code = f'{base_code}_{suffix}'
            suffix += 1
        tx('INSERT INTO games (code, name) VALUES (%s, %s)', (code, name)).close()
        _audit(tx, admin_tg_id, 'create', 'game', code, {'name': name})
        return code


def delete_admin_game(admin_tg_id, code):
    with db.transaction() as tx:
        game = tx('DELETE FROM games WHERE code = %s RETURNING name', (code,)).one()
        if not game:
            raise ValueError('Игра не найдена')
        _audit(tx, admin_tg_id, 'delete', 'game', code, {'name': game['name']})


def update_admin_player(admin_tg_id, user_id, bio, birthday, game_codes, chat_position, version):
    game_codes = sorted(set(game_codes))
    with db.transaction() as tx:
        current = tx(
            'SELECT id, lock_version FROM users WHERE id = %s AND left_at IS NULL FOR UPDATE',
            (user_id,),
        ).one()
        if not current:
            raise ValueError('Игрок не найден')
        if current['lock_version'] != version:
            raise ConcurrentEditError(
                'Профиль уже изменил другой администратор. Проверьте данные и нажмите «Сохранить» ещё раз для перезаписи.'
            )
        valid_games = {row['code'] for row in tx('SELECT code FROM games').all()}
        if not set(game_codes) <= valid_games:
            raise ValueError('Выбрана неизвестная игра')
        tx(
            'UPDATE users SET chat_position = %s, lock_version = lock_version + 1 WHERE id = %s',
            (chat_position or None, user_id),
        ).close()
        tx(
            '''
            INSERT INTO user_card (user_id, bio) VALUES (%s, %s)
            ON CONFLICT (user_id) DO UPDATE SET bio = EXCLUDED.bio
            ''',
            (user_id, bio or None),
        ).close()
        if birthday:
            tx(
                '''
                INSERT INTO birthdays (user_id, day, month, year) VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    day = EXCLUDED.day, month = EXCLUDED.month, year = EXCLUDED.year
                ''',
                (user_id, birthday['day'], birthday['month'], birthday['year']),
            ).close()
        else:
            tx('DELETE FROM birthdays WHERE user_id = %s', (user_id,)).close()
        tx('DELETE FROM user_games WHERE user_id = %s', (user_id,)).close()
        if game_codes:
            tx(
                '''
                INSERT INTO user_games (user_id, game_code)
                SELECT %s, UNNEST(%s::text[])
                ''',
                (user_id, game_codes),
            ).close()
        _audit(tx, admin_tg_id, 'update', 'user', user_id, {
            'birthday': birthday, 'games': game_codes, 'bio_length': len(bio),
            'chat_position': chat_position,
        })


def add_admin_user_title(admin_tg_id, user_id, name):
    with db.transaction() as tx:
        if not tx('SELECT id FROM users WHERE id = %s AND left_at IS NULL', (user_id,)).one():
            raise ValueError('Игрок не найден')
        row = tx(
            '''
            INSERT INTO user_titles (user_id, name) VALUES (%s, %s)
            ON CONFLICT DO NOTHING RETURNING id
            ''',
            (user_id, name),
        ).one()
        if not row:
            raise ValueError('У игрока уже есть такой титул')
        _audit(tx, admin_tg_id, 'create', 'user_title', row['id'], {
            'user_id': user_id, 'name': name,
        })
        return row['id']


def delete_admin_user_title(admin_tg_id, user_id, title_id):
    with db.transaction() as tx:
        row = tx(
            'DELETE FROM user_titles WHERE id = %s AND user_id = %s RETURNING name',
            (title_id, user_id),
        ).one()
        if not row:
            raise ValueError('Титул не найден')
        _audit(tx, admin_tg_id, 'delete', 'user_title', title_id, {
            'user_id': user_id, 'name': row['name'],
        })


def list_admin_characters():
    return db(
        '''
        SELECT c.id, c.name, c.is_primary, c.description, c.birth_date,
            u.id AS owner_id, u.tag AS owner_tag
        FROM character c JOIN users u ON u.id = c.owner_user_id
        ORDER BY c.name
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


def create_admin_position(admin_tg_id, name):
    with db.transaction() as tx:
        row = tx(
            'INSERT INTO positions (name) VALUES (%s) ON CONFLICT DO NOTHING RETURNING id',
            (name,),
        ).one()
        if not row:
            raise ValueError('Должность с таким названием уже существует')
        _audit(tx, admin_tg_id, 'create', 'position', row['id'], {'name': name})
        return row['id']


def update_admin_position(admin_tg_id, position_id, name):
    with db.transaction() as tx:
        current = tx('SELECT id, name FROM positions WHERE id = %s FOR UPDATE', (position_id,)).one()
        if not current:
            raise ValueError('Должность не найдена')
        if tx(
            'SELECT id FROM positions WHERE lower(name) = lower(%s) AND id <> %s',
            (name, position_id),
        ).one():
            raise ValueError('Должность с таким названием уже существует')
        tx('UPDATE positions SET name = %s WHERE id = %s', (name, position_id)).close()
        _audit(tx, admin_tg_id, 'update', 'position', position_id, {
            'from_name': current['name'], 'to_name': name,
        })


def delete_admin_position(admin_tg_id, position_id):
    with db.transaction() as tx:
        row = tx('DELETE FROM positions WHERE id = %s RETURNING name', (position_id,)).one()
        if not row:
            raise ValueError('Должность не найдена')
        _audit(tx, admin_tg_id, 'delete', 'position', position_id, {'name': row['name']})


def _validate_character_position(tx, position_id, character_id=None):
    if position_id is None:
        return
    if not tx('SELECT id FROM positions WHERE id = %s', (position_id,)).one():
        raise ValueError('Выбрана неизвестная должность')


def create_character(
    admin_tg_id, owner_user_id, name, birth_date=None, description=None, is_primary=False,
    position_id=None, wiki_url=None, photo_file_id=None,
):
    with db.transaction() as tx:
        if not tx('SELECT 1 FROM users WHERE id = %s FOR UPDATE', (owner_user_id,)).one():
            raise ValueError('Игрок не найден')
        if tx('SELECT 1 FROM character WHERE lower(name) = lower(%s)', (name,)).one():
            raise ValueError('Персонаж с таким именем уже существует')
        _validate_character_position(tx, position_id)
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
            INSERT INTO character (
                owner_user_id, name, birth_date, description, is_primary, position_id,
                wiki_url, photo_file_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            ''',
            (owner_user_id, name, birth_date, description, primary, position_id, wiki_url, photo_file_id),
        ).one()
        _audit(tx, admin_tg_id, 'create', 'character', row['id'], {
            'owner_user_id': owner_user_id, 'name': name, 'position_id': position_id,
        })
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


def get_admin_character(character_id):
    return db('SELECT * FROM character WHERE id = %s', (character_id,)).one()


def update_character(
    admin_tg_id, character_id, name, birth_date=None, description=None, wiki_url=None,
    position_id=None, version=None, photo_file_id=_UNSET,
):
    with db.transaction() as tx:
        current = tx(
            'SELECT lock_version FROM character WHERE id = %s FOR UPDATE', (character_id,),
        ).one()
        if not current:
            raise ValueError('Персонаж не найден')
        if current['lock_version'] != version:
            raise ConcurrentEditError(
                'Персонажа уже изменил другой администратор. Проверьте данные и нажмите «Сохранить» ещё раз для перезаписи.'
            )
        if tx(
            'SELECT 1 FROM character WHERE lower(name) = lower(%s) AND id <> %s',
            (name, character_id),
        ).one():
            raise ValueError('Персонаж с таким именем уже существует')
        _validate_character_position(tx, position_id, character_id)
        photo_assignment = '' if photo_file_id is _UNSET else ', photo_file_id = %s'
        params = [name, birth_date, description, wiki_url, position_id]
        if photo_file_id is not _UNSET:
            params.append(photo_file_id)
        params.append(character_id)
        tx(
            f'''
            UPDATE character
            SET name = %s, birth_date = %s, description = %s, wiki_url = %s, position_id = %s,
                lock_version = lock_version + 1{photo_assignment}
            WHERE id = %s
            ''',
            tuple(params),
        ).close()
        _audit(tx, admin_tg_id, 'update', 'character', character_id, {
            'name': name, 'position_id': position_id, 'photo_changed': photo_file_id is not _UNSET,
        })


def delete_character(admin_tg_id, character_id):
    with db.transaction() as tx:
        character = tx('DELETE FROM character WHERE id = %s RETURNING *', (character_id,)).one()
        if not character:
            raise ValueError('Персонаж не найден')
        if character['is_primary']:
            tx(
                '''
                UPDATE character SET is_primary = TRUE WHERE id = (
                    SELECT id FROM character WHERE owner_user_id = %s ORDER BY created_at, id LIMIT 1
                )
                ''',
                (character['owner_user_id'],),
            ).close()
        _audit(tx, admin_tg_id, 'delete', 'character', character_id, {'name': character['name']})


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


def get_tag_usage_bounds():
    return db('SELECT MIN(used_at) AS first, MAX(used_at) AS last FROM tag_usage').one()


def get_tag_usage_series(start, end, interval):
    if interval not in {'5 minutes', '1 hour', '1 day', '1 month'}:
        raise ValueError('Неизвестный интервал группировки')
    return db(
        '''
        WITH bounds AS (
            SELECT %s::timestamptz AS start_at, %s::timestamptz AS end_at, %s::interval AS bucket
        )
        SELECT d.bucket AS day, COUNT(tu.id) AS total,
            COUNT(tu.id) FILTER (WHERE tu.media_type = 'photo') AS photo,
            COUNT(tu.id) FILTER (WHERE tu.media_type = 'video') AS video,
            COUNT(tu.id) FILTER (WHERE tu.media_type = 'video_link') AS video_link
        FROM bounds
        CROSS JOIN LATERAL generate_series(
            bounds.start_at, GREATEST(bounds.start_at, bounds.end_at - bounds.bucket), bounds.bucket
        ) d(bucket)
        LEFT JOIN tag_usage tu ON tu.used_at >= d.bucket AND tu.used_at < d.bucket + bounds.bucket
            AND tu.used_at >= bounds.start_at AND tu.used_at < bounds.end_at
        GROUP BY d.bucket ORDER BY d.bucket
        ''',
        (start, end, interval),
    ).all()


def get_tag_subscription_popularity():
    return db(
        '''
        SELECT t.id, t.name, COUNT(s.id) AS cnt
        FROM subscription s
        JOIN tag t ON t.id = s.tag_id
        WHERE s.active = TRUE
        GROUP BY t.id, t.name
        ORDER BY cnt DESC, t.name
        '''
    ).all()


def get_recent_audit(limit=10):
    return db('SELECT * FROM admin_audit_log ORDER BY created_at DESC LIMIT %s', (limit,)).all()
