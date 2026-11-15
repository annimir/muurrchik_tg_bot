from database.queries import db
from services.tierlist_catalog import (
    RANKED_TIER_CODES,
    TIER_CODES,
    list_tierlist_characters,
    tierlist_game_codes,
)


class TierListConflictError(ValueError):
    pass


def _title(value):
    title = (value or '').strip()
    if not title or len(title) > 100:
        raise ValueError('Название должно содержать от 1 до 100 символов')
    return title


def _games(game_codes):
    games = sorted(set(game_codes))
    if not games or not set(games) <= set(tierlist_game_codes()):
        raise ValueError('Выберите хотя бы одну доступную игру')
    return games


def _insert_games(tx, tier_list_id, game_codes):
    for game_code in game_codes:
        tx(
            'INSERT INTO tier_list_game (tier_list_id, game_code) VALUES (%s, %s)',
            (tier_list_id, game_code),
        ).close()


def create_tier_list(user_id, title, game_codes):
    title = _title(title)
    games = _games(game_codes)
    characters = list_tierlist_characters(games)
    with db.transaction() as tx:
        row = tx(
            '''
            INSERT INTO tier_list (user_id, title)
            SELECT id, %s FROM users WHERE id = %s
            RETURNING id
            ''',
            (title, user_id),
        ).one()
        if not row:
            raise ValueError('Игрок не найден')
        tier_list_id = row['id']
        _insert_games(tx, tier_list_id, games)
        for position, character in enumerate(characters):
            tx(
                '''
                INSERT INTO tier_list_entry (tier_list_id, character_id, tier, position)
                VALUES (%s, %s, 'UNRANKED', %s)
                ''',
                (tier_list_id, character['id'], position),
            ).close()
    return get_tier_list(tier_list_id, user_id)


def list_user_tier_lists(user_id):
    return db(
        '''
        SELECT tl.id, tl.title, tl.updated_at,
            COALESCE((SELECT array_agg(g.name ORDER BY g.name)
                FROM tier_list_game tlg JOIN games g ON g.code = tlg.game_code
                WHERE tlg.tier_list_id = tl.id), ARRAY[]::text[]) AS game_names,
            (SELECT COUNT(*) FROM tier_list_entry tle
                WHERE tle.tier_list_id = tl.id AND tle.tier <> 'UNRANKED') AS ranked_count
        FROM tier_list tl
        WHERE tl.user_id = %s
        ORDER BY tl.updated_at DESC, tl.id DESC
        ''',
        (user_id,),
    ).all()


def list_public_tier_lists():
    return db(
        '''
        SELECT tl.id, tl.title, tl.updated_at, u.id AS owner_id, u.tag AS owner_tag,
            COALESCE((SELECT array_agg(g.name ORDER BY g.name)
                FROM tier_list_game tlg JOIN games g ON g.code = tlg.game_code
                WHERE tlg.tier_list_id = tl.id), ARRAY[]::text[]) AS game_names,
            (SELECT COUNT(*) FROM tier_list_entry tle
                WHERE tle.tier_list_id = tl.id AND tle.tier <> 'UNRANKED') AS ranked_count
        FROM tier_list tl
        JOIN users u ON u.id = tl.user_id AND u.left_at IS NULL
        ORDER BY tl.updated_at DESC, tl.id DESC
        '''
    ).all()


def attach_tier_list_previews(tier_lists, per_tier=6):
    if not tier_lists:
        return tier_lists
    ids = [tier_list['id'] for tier_list in tier_lists]
    entries = db(
        '''
        SELECT tier_list_id, character_id, tier FROM tier_list_entry
        WHERE tier_list_id = ANY(%s) AND tier <> 'UNRANKED'
        ORDER BY tier_list_id, tier, position, character_id
        ''',
        (ids,),
    ).all()
    characters = {character['id']: character for character in list_tierlist_characters()}
    previews = {
        tier_list_id: {tier: [] for tier in RANKED_TIER_CODES}
        for tier_list_id in ids
    }
    for entry in entries:
        row = previews[entry['tier_list_id']][entry['tier']]
        character = characters.get(entry['character_id'])
        if character and len(row) < per_tier:
            row.append(character)
    for tier_list in tier_lists:
        previews_for_list = previews[tier_list['id']]
        tier_list['preview_rows'] = [
            {'code': tier, 'characters': previews_for_list[tier]}
            for tier in RANKED_TIER_CODES
            if previews_for_list[tier]
        ]
    return tier_lists


def get_tier_list(tier_list_id, owner_user_id=None):
    visibility = 'AND u.left_at IS NULL' if owner_user_id is None else ''
    tier_list = db(
        f'''
        SELECT tl.*, u.tag AS owner_tag
        FROM tier_list tl JOIN users u ON u.id = tl.user_id
        WHERE tl.id = %s {visibility}
        ''',
        (tier_list_id,),
    ).one()
    if not tier_list:
        return None
    if owner_user_id is not None and tier_list['user_id'] != owner_user_id:
        return None
    tier_list['game_codes'] = [
        row['game_code'] for row in db(
            'SELECT game_code FROM tier_list_game WHERE tier_list_id = %s ORDER BY game_code',
            (tier_list_id,),
        ).all()
    ]
    tier_list['game_names'] = [
        row['name'] for row in db(
            '''
            SELECT g.name FROM tier_list_game tlg JOIN games g ON g.code = tlg.game_code
            WHERE tlg.tier_list_id = %s ORDER BY g.name
            ''',
            (tier_list_id,),
        ).all()
    ]
    tier_list['entries'] = db(
        '''
        SELECT character_id, tier, position FROM tier_list_entry
        WHERE tier_list_id = %s ORDER BY tier, position, character_id
        ''',
        (tier_list_id,),
    ).all()
    return tier_list


def update_tier_list(user_id, tier_list_id, title, game_codes, entries, version):
    title = _title(title)
    games = _games(game_codes)
    characters = {character['id'] for character in list_tierlist_characters(games)}
    if len(entries) != len(characters):
        raise ValueError('Раскладка не содержит всех персонажей выбранных игр')
    character_ids = [entry.get('character_id') for entry in entries]
    if len(set(character_ids)) != len(character_ids) or set(character_ids) != characters:
        raise ValueError('Персонажи раскладки не соответствуют выбранным играм')
    if any(entry.get('tier') not in TIER_CODES for entry in entries):
        raise ValueError('Неизвестный тир')

    positions = dict.fromkeys(TIER_CODES, 0)
    normalized_entries = []
    for entry in entries:
        tier = entry['tier']
        normalized_entries.append((entry['character_id'], tier, positions[tier]))
        positions[tier] += 1

    with db.transaction() as tx:
        current = tx(
            'SELECT user_id, lock_version FROM tier_list WHERE id = %s FOR UPDATE',
            (tier_list_id,),
        ).one()
        if not current or current['user_id'] != user_id:
            raise ValueError('Тирлист не найден')
        if current['lock_version'] != version:
            raise TierListConflictError('Тирлист уже изменён в другой вкладке')
        updated = tx(
            '''
            UPDATE tier_list
            SET title = %s, lock_version = lock_version + 1, updated_at = now()
            WHERE id = %s
            ''',
            (title, tier_list_id),
        )
        updated.close()
        tx('DELETE FROM tier_list_game WHERE tier_list_id = %s', (tier_list_id,)).close()
        _insert_games(tx, tier_list_id, games)
        tx('DELETE FROM tier_list_entry WHERE tier_list_id = %s', (tier_list_id,)).close()
        for character_id, tier, position in normalized_entries:
            tx(
                '''
                INSERT INTO tier_list_entry (tier_list_id, character_id, tier, position)
                VALUES (%s, %s, %s, %s)
                ''',
                (tier_list_id, character_id, tier, position),
            ).close()
    return get_tier_list(tier_list_id, user_id)


def delete_tier_list(user_id, tier_list_id):
    return db(
        'DELETE FROM tier_list WHERE id = %s AND user_id = %s RETURNING id',
        (tier_list_id, user_id),
    ).one()


def ranked_entries(tier_list):
    return [entry for entry in tier_list['entries'] if entry['tier'] in RANKED_TIER_CODES]
