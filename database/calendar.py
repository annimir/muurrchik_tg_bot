import json
from datetime import date
from urllib.parse import urlparse

from database.queries import db

EVENT_TYPES = {'event', 'banner', 'stream'}


def _date_value(value, label):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f'Укажите {label} в формате ГГГГ-ММ-ДД') from None


def _values(game_code, title, description, event_type, start_date, end_date, url):
    title = (title or '').strip()
    description = (description or '').strip()
    url = (url or '').strip()
    start_date = _date_value(start_date, 'дату начала')
    end_date = _date_value(end_date, 'дату окончания')
    if not 1 <= len(title) <= 120:
        raise ValueError('Название должно содержать от 1 до 120 символов')
    if len(description) > 1000:
        raise ValueError('Описание должно содержать не более 1000 символов')
    if event_type not in EVENT_TYPES:
        raise ValueError('Выберите тип события: ивент, баннер или стрим')
    if end_date < start_date:
        raise ValueError('Дата окончания не может быть раньше даты начала')
    if len(url) > 500:
        raise ValueError('Ссылка должна содержать не более 500 символов')
    if url and (urlparse(url).scheme not in {'http', 'https'} or not urlparse(url).netloc):
        raise ValueError('Ссылка должна начинаться с http:// или https://')
    return game_code, title, description, event_type, start_date, end_date, url or None


def _audit(tx, admin_tg_id, action, event_id, details):
    tx(
        '''
        INSERT INTO admin_audit_log (admin_tg_id, action, entity_type, entity_id, details)
        VALUES (%s, %s, 'calendar_event', %s, %s::jsonb)
        ''',
        (admin_tg_id, action, str(event_id), json.dumps(details, ensure_ascii=False)),
    ).close()


def _check_game(tx, game_code):
    if not tx('SELECT code FROM games WHERE code = %s', (game_code,)).one():
        raise ValueError('Игра не найдена')


def list_calendar_events(month_start, next_month, game_code='', event_type=''):
    query = '''
        SELECT e.*, g.name AS game_name
        FROM calendar_event e JOIN games g ON g.code = e.game_code
        WHERE e.start_date < %s AND e.end_date >= %s
    '''
    params = [next_month, month_start]
    if game_code:
        query += ' AND e.game_code = %s'
        params.append(game_code)
    if event_type:
        query += ' AND e.event_type = %s'
        params.append(event_type)
    query += ' ORDER BY e.start_date, e.end_date, e.id'
    return db(query, tuple(params)).all()


def list_admin_calendar_events():
    return db(
        '''
        SELECT e.*, g.name AS game_name
        FROM calendar_event e JOIN games g ON g.code = e.game_code
        ORDER BY e.start_date DESC, e.id DESC
        '''
    ).all()


def get_calendar_event(event_id):
    return db('SELECT * FROM calendar_event WHERE id = %s', (event_id,)).one()


def list_player_birthdays():
    return db(
        '''
        SELECT u.id, u.tag, b.day, b.month
        FROM birthdays b JOIN users u ON u.id = b.user_id
        WHERE u.left_at IS NULL
        ORDER BY b.month, b.day, u.tag
        '''
    ).all()


def list_character_birthdays():
    return db(
        '''
        SELECT c.id, c.name, c.birth_date, u.id AS owner_id, u.tag AS owner_tag
        FROM character c JOIN users u ON u.id = c.owner_user_id
        WHERE c.birth_date IS NOT NULL AND u.left_at IS NULL
        ORDER BY c.name
        '''
    ).all()


def create_calendar_event(
    admin_tg_id, game_code, title, description, event_type, start_date, end_date, url='',
):
    values = _values(game_code, title, description, event_type, start_date, end_date, url)
    with db.transaction() as tx:
        _check_game(tx, game_code)
        row = tx(
            '''
            INSERT INTO calendar_event (
                game_code, title, description, event_type, start_date, end_date, url, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *
            ''',
            (*values, admin_tg_id),
        ).one()
        _audit(tx, admin_tg_id, 'create', row['id'], {'title': row['title']})
        return row


def update_calendar_event(
    admin_tg_id, event_id, game_code, title, description, event_type, start_date, end_date, url='',
):
    values = _values(game_code, title, description, event_type, start_date, end_date, url)
    with db.transaction() as tx:
        _check_game(tx, game_code)
        row = tx(
            '''
            UPDATE calendar_event
            SET game_code = %s, title = %s, description = %s, event_type = %s,
                start_date = %s, end_date = %s, url = %s, updated_at = now()
            WHERE id = %s RETURNING *
            ''',
            (*values, event_id),
        ).one()
        if not row:
            raise ValueError('Событие не найдено')
        _audit(tx, admin_tg_id, 'update', event_id, {'title': row['title']})
        return row


def delete_calendar_event(admin_tg_id, event_id):
    with db.transaction() as tx:
        row = tx('DELETE FROM calendar_event WHERE id = %s RETURNING title', (event_id,)).one()
        if not row:
            raise ValueError('Событие не найдено')
        _audit(tx, admin_tg_id, 'delete', event_id, {'title': row['title']})
