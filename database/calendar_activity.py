import calendar as month_calendar
import json
from datetime import date, timedelta

from database.queries import db

SCHEDULE_RULES = {'month_start', 'month_16', 'patch_day8'}


def seed_calendar_activities():
    db(
        '''
        INSERT INTO calendar_activity (game_code, code, name, description, schedule_rule)
        SELECT 'genshin', values.code, values.name, values.description, values.schedule_rule
        FROM (VALUES
            ('theater', 'Театр Воображариума', 'Ежемесячный Театр Воображариума', 'month_start'),
            ('abyss', 'Витая Бездна', 'Ежемесячный цикл Витой Бездны', 'month_16'),
            ('onslaught', 'Мрачный натиск', 'Натиск начинается на восьмой день патча', 'patch_day8')
        ) AS values(code, name, description, schedule_rule)
        WHERE EXISTS (SELECT 1 FROM games WHERE code = 'genshin')
        ON CONFLICT (game_code, code) DO NOTHING
        '''
    ).close()


def _date(value, label):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'Укажите {label}') from None


def cycle_dates(activity, cycle_month='', patch_start='', start_date='', end_date=''):
    if start_date or end_date:
        start = _date(start_date, 'дату начала')
        end = _date(end_date, 'дату окончания')
    elif activity['schedule_rule'] in {'month_start', 'month_16'}:
        try:
            year, month = map(int, cycle_month.split('-'))
            start = date(year, month, 1 if activity['schedule_rule'] == 'month_start' else 16)
        except (TypeError, ValueError):
            raise ValueError('Выберите месяц цикла') from None
        if activity['schedule_rule'] == 'month_start':
            end = date(year, month, month_calendar.monthrange(year, month)[1])
        else:
            next_month = date(year + (month == 12), month % 12 + 1, 16)
            end = next_month - timedelta(days=1)
    elif activity['schedule_rule'] == 'patch_day8':
        patch = _date(patch_start, 'дату начала патча')
        start = patch + timedelta(days=7)
        end = start + timedelta(days=34)
    else:
        raise ValueError('Неизвестное правило расписания')
    if end < start:
        raise ValueError('Дата окончания не может быть раньше даты начала')
    return start, end


def _details(activity_code, details):
    if activity_code == 'onslaught':
        bosses = [str(value).strip() for value in details.get('bosses', [])]
        if len(bosses) != 3 or any(not 1 <= len(value) <= 120 for value in bosses):
            raise ValueError('Укажите имена трёх боссов')
        return {'bosses': bosses}
    if activity_code == 'theater':
        from services.tierlist_catalog import (
            get_tierlist_character, get_tierlist_filter_options,
        )

        elements = list(dict.fromkeys(details.get('elements', [])))
        allowed = {
            option['id'] for option in get_tierlist_filter_options(['genshin'])['element']
        }
        if len(elements) != 3 or not set(elements) <= allowed:
            raise ValueError('Выберите три разные стихии')
        characters = list(dict.fromkeys(details.get('invited_characters', [])))
        if not 1 <= len(characters) <= 20:
            raise ValueError('Выберите от 1 до 20 приглашённых персонажей')
        for character_id in characters:
            character = get_tierlist_character(character_id)
            if not character or character['game'] != 'genshin':
                raise ValueError('Приглашённый персонаж не найден')
        return {'elements': elements, 'invited_characters': characters}
    if activity_code == 'abyss':
        first = str(details.get('first_half', '')).strip()
        second = str(details.get('second_half', '')).strip()
        if not 1 <= len(first) <= 500 or not 1 <= len(second) <= 500:
            raise ValueError('Укажите бонусы обеих половин 12-го этажа')
        return {'first_half': first, 'second_half': second}
    raise ValueError('Неизвестный тип активности')


def list_calendar_activities(game_code=''):
    query = 'SELECT * FROM calendar_activity WHERE is_active'
    params = []
    if game_code:
        query += ' AND game_code = %s'
        params.append(game_code)
    query += ' ORDER BY id'
    return db(query, tuple(params)).all()


def get_calendar_activity(activity_id):
    return db('SELECT * FROM calendar_activity WHERE id = %s', (activity_id,)).one()


def list_activity_cycles(month_start, next_month, game_code=''):
    query = '''
        SELECT c.*, a.code AS activity_code, a.name AS activity_name,
            a.description AS activity_description, a.game_code, g.name AS game_name
        FROM calendar_activity_cycle c
        JOIN calendar_activity a ON a.id = c.activity_id
        JOIN games g ON g.code = a.game_code
        WHERE a.is_active AND c.start_date < %s AND c.end_date >= %s
    '''
    params = [next_month, month_start]
    if game_code:
        query += ' AND a.game_code = %s'
        params.append(game_code)
    query += ' ORDER BY a.id, c.start_date'
    return db(query, tuple(params)).all()


def list_admin_activity_cycles():
    return db(
        '''
        SELECT c.*, a.code AS activity_code, a.name AS activity_name,
            a.game_code, g.name AS game_name
        FROM calendar_activity_cycle c
        JOIN calendar_activity a ON a.id = c.activity_id
        JOIN games g ON g.code = a.game_code
        ORDER BY c.start_date DESC, c.id DESC
        '''
    ).all()


def get_activity_cycle(cycle_id):
    return db(
        '''
        SELECT c.*, a.code AS activity_code, a.name AS activity_name,
            a.description AS activity_description, a.schedule_rule, a.game_code,
            g.name AS game_name
        FROM calendar_activity_cycle c
        JOIN calendar_activity a ON a.id = c.activity_id
        JOIN games g ON g.code = a.game_code
        WHERE c.id = %s
        ''',
        (cycle_id,),
    ).one()


def _audit(tx, admin_tg_id, action, cycle_id, activity_name):
    tx(
        '''
        INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id, details)
        VALUES (%s, %s, 'calendar_activity_cycle', %s, %s::jsonb)
        ''',
        (admin_tg_id, action, str(cycle_id), json.dumps({'activity': activity_name}, ensure_ascii=False)),
    ).close()


def create_activity_cycle(
    admin_tg_id, activity_id, details, cycle_month='', patch_start='', start_date='', end_date='',
):
    activity = get_calendar_activity(activity_id)
    if not activity or not activity['is_active']:
        raise ValueError('Активность не найдена')
    start, end = cycle_dates(activity, cycle_month, patch_start, start_date, end_date)
    normalized = _details(activity['code'], details)
    with db.transaction() as tx:
        row = tx(
            '''
            INSERT INTO calendar_activity_cycle (activity_id, start_date, end_date, details, created_by)
            VALUES (%s, %s, %s, %s::jsonb, %s) RETURNING id
            ''',
            (activity_id, start, end, json.dumps(normalized, ensure_ascii=False), admin_tg_id),
        ).one()
        _audit(tx, admin_tg_id, 'create', row['id'], activity['name'])
    return get_activity_cycle(row['id'])


def update_activity_cycle(
    admin_tg_id, cycle_id, activity_id, details,
    cycle_month='', patch_start='', start_date='', end_date='',
):
    activity = get_calendar_activity(activity_id)
    if not activity:
        raise ValueError('Активность не найдена')
    start, end = cycle_dates(activity, cycle_month, patch_start, start_date, end_date)
    normalized = _details(activity['code'], details)
    with db.transaction() as tx:
        row = tx(
            '''
            UPDATE calendar_activity_cycle
            SET activity_id = %s, start_date = %s, end_date = %s, details = %s::jsonb,
                updated_at = now()
            WHERE id = %s RETURNING id
            ''',
            (activity_id, start, end, json.dumps(normalized, ensure_ascii=False), cycle_id),
        ).one()
        if not row:
            raise ValueError('Цикл не найден')
        _audit(tx, admin_tg_id, 'update', cycle_id, activity['name'])
    return get_activity_cycle(cycle_id)


def delete_activity_cycle(admin_tg_id, cycle_id):
    cycle = get_activity_cycle(cycle_id)
    if not cycle:
        return
    db('DELETE FROM calendar_activity_cycle WHERE id = %s', (cycle_id,)).close()
    with db.transaction() as tx:
        _audit(tx, admin_tg_id, 'delete', cycle_id, cycle['activity_name'])
