import hashlib
import json
import re
import threading
from functools import lru_cache
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parent.parent / 'web' / 'content' / 'tierlist_characters.json'
TIER_CODES = ('S', 'A', 'B', 'C', 'D', 'UNRANKED')
RANKED_TIER_CODES = TIER_CODES[:-1]
AVAILABILITY_CODES = {'playable', 'upcoming', 'npc'}
ID_PATTERN = re.compile(r'[a-z0-9][a-z0-9_-]{0,79}')
LOCAL_IMAGE_PATTERN = re.compile(r'/media/tierlists/[a-f0-9]{32}\.(jpg|png|webp)')
REQUIRED_KEYS = {
    'id', 'name', 'game', 'region', 'element', 'gender', 'rarity', 'release', 'image',
}
OPTIONAL_KEYS = {'affiliations', 'availability'}
CATALOG_LOCK_ID = 741852963
_sync_lock = threading.Lock()
_synchronized = False


class TierListCatalogConflictError(ValueError):
    pass


@lru_cache(maxsize=1)
def _characters():
    with CATALOG_PATH.open(encoding='utf-8') as file:
        return tuple(json.load(file))


def _sync_bundled_characters():
    global _synchronized
    if _synchronized:
        return
    with _sync_lock:
        if _synchronized:
            return
        from database.queries import db

        with db.transaction() as tx:
            for position, character in enumerate(_characters()):
                tx(
                    '''
                    INSERT INTO tier_list_catalog_character (id, game_code, data, position)
                    VALUES (%s, %s, %s::jsonb, %s)
                    ON CONFLICT (id) DO NOTHING
                    ''',
                    (
                        character['id'], character['game'],
                        json.dumps(character, ensure_ascii=False), position,
                    ),
                ).close()
        _synchronized = True


def reset_tierlist_catalog_cache():
    global _synchronized
    _synchronized = False


def list_tierlist_characters(game_codes=()):
    _sync_bundled_characters()
    from database.queries import db

    allowed = set(game_codes)
    rows = db(
        '''
        SELECT data FROM tier_list_catalog_character
        WHERE is_active ORDER BY position, id
        ''',
    ).all()
    return [
        row['data'] for row in rows
        if not allowed or row['data']['game'] in allowed
    ]


def get_tierlist_character_record(character_id):
    _sync_bundled_characters()
    from database.queries import db

    return db(
        '''
        SELECT data, lock_version FROM tier_list_catalog_character
        WHERE id = %s AND is_active
        ''',
        (character_id,),
    ).one()


def get_tierlist_character(character_id):
    record = get_tierlist_character_record(character_id)
    return record['data'] if record else None


def get_tierlist_filter_options(game_codes=()):
    characters = list_tierlist_characters(game_codes)
    options = {
        key: sorted(
            {character[key]['id']: character[key] for character in characters}.values(),
            key=lambda value: value['name'].casefold(),
        )
        for key in ('region', 'element', 'gender')
    }
    options['affiliation'] = sorted(
        {
            affiliation['id']: affiliation
            for character in characters
            for affiliation in character.get('affiliations', [])
        }.values(),
        key=lambda value: value['name'].casefold(),
    )
    options['rarity'] = [
        {'id': str(rarity), 'name': f'{rarity}★'}
        for rarity in sorted({character['rarity'] for character in characters if character['rarity'] is not None})
    ]
    return options


def tierlist_game_codes():
    return sorted({character['game'] for character in list_tierlist_characters()})


def _text(value, label, maximum=100):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise ValueError(f'{label} должно содержать от 1 до {maximum} символов')
    return value.strip()


def _id(value, label):
    value = _text(value, label, 80)
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(f'{label} может содержать только строчные латинские буквы, цифры, _ и -')
    return value


def _metadata(value, label):
    if not isinstance(value, dict) or set(value) != {'id', 'name'}:
        raise ValueError(f'{label} должно быть объектом с полями id и name')
    return {'id': _id(value['id'], f'{label}.id'), 'name': _text(value['name'], f'{label}.name')}


def _image(value):
    value = _text(value, 'Изображение', 300)
    if LOCAL_IMAGE_PATTERN.fullmatch(value):
        return value
    if value.startswith('/static/tierlists/') and '..' not in value:
        path = Path('web') / value.removeprefix('/')
        if path.is_file():
            return value
        raise ValueError('Файл изображения не найден')
    raise ValueError('Изображение должно быть файлом каталога или загруженным PNG/JPEG/WEBP')


def _validate_character(character, game_codes):
    if not isinstance(character, dict):
        raise ValueError('Каждый персонаж должен быть JSON-объектом')
    keys = set(character)
    if not REQUIRED_KEYS <= keys or not keys <= REQUIRED_KEYS | OPTIONAL_KEYS:
        raise ValueError('Проверьте обязательные и неизвестные поля персонажа')
    character_id = _id(character['id'], 'ID')
    game = _id(character['game'], 'Игра')
    if game not in game_codes:
        raise ValueError(f'Игра {game} не найдена. Сначала добавьте её в разделе «Игры»')
    rarity = character['rarity']
    if rarity is not None and (type(rarity) is not int or not 1 <= rarity <= 5):
        raise ValueError(f'{character_id}: редкость должна быть целым числом от 1 до 5 или null')
    release = character['release']
    if release is not None and (type(release) is not int or release < 0):
        raise ValueError(f'{character_id}: release должен быть неотрицательным Unix-временем или null')
    availability = character.get('availability', 'playable')
    if availability not in AVAILABILITY_CODES:
        raise ValueError(f'{character_id}: неизвестный тип {availability}')
    affiliations = character.get('affiliations', [])
    if not isinstance(affiliations, list):
        raise ValueError(f'{character_id}: affiliations должен быть массивом')
    normalized = {
        'id': character_id,
        'name': _text(character['name'], 'Имя'),
        'game': game,
        'region': _metadata(character['region'], 'Регион'),
        'element': _metadata(character['element'], 'Стихия'),
        'gender': _metadata(character['gender'], 'Пол'),
        'rarity': rarity,
        'release': release,
        'image': _image(character['image']),
    }
    if 'availability' in character:
        normalized['availability'] = availability
    if affiliations or 'affiliations' in character:
        normalized['affiliations'] = [
            _metadata(affiliation, 'Фракция') for affiliation in affiliations
        ]
    return normalized


def validate_tierlist_catalog(payload):
    if not isinstance(payload, list) or not 1 <= len(payload) <= 2000:
        raise ValueError('Каталог должен быть JSON-массивом с 1–2000 персонажами')
    from database.queries import db

    game_codes = {row['code'] for row in db('SELECT code FROM games').all()}
    characters = [_validate_character(character, game_codes) for character in payload]
    ids = [character['id'] for character in characters]
    if len(ids) != len(set(ids)):
        raise ValueError('ID персонажей должны быть уникальными')
    return characters


def tierlist_catalog_json(characters):
    return json.dumps(characters, ensure_ascii=False, indent=2)


def tierlist_catalog_version(characters=None):
    characters = list_tierlist_characters() if characters is None else characters
    serialized = json.dumps(characters, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _audit(tx, admin_tg_id, action, character_id, details):
    tx(
        '''
        INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id, details)
        VALUES (%s, %s, 'tierlist_catalog', %s, %s::jsonb)
        ''',
        (admin_tg_id, action, character_id, json.dumps(details, ensure_ascii=False)),
    ).close()


def save_tierlist_character(admin_tg_id, character_id, payload, version=None):
    character = validate_tierlist_catalog([payload])[0]
    if version is not None and character['id'] != character_id:
        raise ValueError('ID существующего персонажа нельзя изменить')
    from database.queries import db

    with db.transaction() as tx:
        tx('SELECT pg_advisory_xact_lock(%s)', (CATALOG_LOCK_ID,)).close()
        if version is None:
            if tx('SELECT 1 FROM tier_list_catalog_character WHERE id = %s', (character['id'],)).one():
                raise ValueError('Персонаж с таким ID уже существует')
            row = tx(
                'SELECT COALESCE(MAX(position), -1) + 1 AS position FROM tier_list_catalog_character',
            ).one()
            tx(
                '''
                INSERT INTO tier_list_catalog_character (
                    id, game_code, data, position, updated_by
                ) VALUES (%s, %s, %s::jsonb, %s, %s)
                ''',
                (
                    character['id'], character['game'],
                    json.dumps(character, ensure_ascii=False), row['position'], admin_tg_id,
                ),
            ).close()
            _audit(tx, admin_tg_id, 'create', character['id'], {'game': character['game']})
            return character

        current = tx(
            '''
            SELECT lock_version FROM tier_list_catalog_character
            WHERE id = %s AND is_active FOR UPDATE
            ''',
            (character_id,),
        ).one()
        if not current:
            raise ValueError('Персонаж не найден')
        if current['lock_version'] != version:
            raise TierListCatalogConflictError('Персонаж уже изменён в другой вкладке')
        tx(
            '''
            UPDATE tier_list_catalog_character
            SET game_code = %s, data = %s::jsonb, lock_version = lock_version + 1,
                updated_at = now(), updated_by = %s
            WHERE id = %s
            ''',
            (
                character['game'], json.dumps(character, ensure_ascii=False),
                admin_tg_id, character_id,
            ),
        ).close()
        _audit(tx, admin_tg_id, 'update', character_id, {'game': character['game']})
        return character


def save_tierlist_catalog(admin_tg_id, payload, expected_version):
    characters = validate_tierlist_catalog(payload)
    from database.queries import db

    with db.transaction() as tx:
        tx('SELECT pg_advisory_xact_lock(%s)', (CATALOG_LOCK_ID,)).close()
        rows = tx(
            'SELECT data FROM tier_list_catalog_character WHERE is_active ORDER BY position, id',
        ).all()
        current = [row['data'] for row in rows]
        if tierlist_catalog_version(current) != expected_version:
            raise TierListCatalogConflictError('Каталог уже изменён в другой вкладке')
        for position, character in enumerate(characters):
            tx(
                '''
                INSERT INTO tier_list_catalog_character (
                    id, game_code, data, position, is_active, updated_by
                ) VALUES (%s, %s, %s::jsonb, %s, TRUE, %s)
                ON CONFLICT (id) DO UPDATE SET
                    game_code = EXCLUDED.game_code, data = EXCLUDED.data,
                    position = EXCLUDED.position, is_active = TRUE,
                    lock_version = tier_list_catalog_character.lock_version + 1,
                    updated_at = now(), updated_by = EXCLUDED.updated_by
                ''',
                (
                    character['id'], character['game'],
                    json.dumps(character, ensure_ascii=False), position, admin_tg_id,
                ),
            ).close()
        ids = [character['id'] for character in characters]
        tx(
            '''
            UPDATE tier_list_catalog_character SET is_active = FALSE,
                lock_version = lock_version + 1, updated_at = now(), updated_by = %s
            WHERE is_active AND id <> ALL(%s)
            ''',
            (admin_tg_id, ids),
        ).close()
        _audit(tx, admin_tg_id, 'bulk_update', 'catalog', {'characters': len(characters)})
    return characters


def delete_tierlist_character(admin_tg_id, character_id):
    from database.queries import db

    with db.transaction() as tx:
        tx('SELECT pg_advisory_xact_lock(%s)', (CATALOG_LOCK_ID,)).close()
        row = tx(
            '''
            UPDATE tier_list_catalog_character
            SET is_active = FALSE, lock_version = lock_version + 1,
                updated_at = now(), updated_by = %s
            WHERE id = %s AND is_active
            RETURNING data
            ''',
            (admin_tg_id, character_id),
        ).one()
        if not row:
            raise ValueError('Персонаж не найден')
        _audit(tx, admin_tg_id, 'delete', character_id, {})
        return row['data']
