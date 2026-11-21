import calendar as month_calendar
from datetime import date, timedelta
from urllib.parse import urlencode

from database.calendar import (
    list_calendar_events, list_character_birthdays, list_player_birthdays,
)
from web.queries import list_games

EVENT_TYPE_LABELS = {
    'event': 'Ивент',
    'banner': 'Баннер',
    'player_birthday': 'День рождения игрока',
    'character_birthday': 'День рождения персонажа',
}
MONTH_NAMES = (
    '', 'Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
    'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь',
)
WEEKDAYS = ('Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс')


def _url(year, month, game_code, event_type):
    params = {'year': year, 'month': month}
    if game_code:
        params['game'] = game_code
    if event_type:
        params['type'] = event_type
    return f'/calendar?{urlencode(params)}'


def _date_range(start_date, end_date):
    if start_date == end_date:
        return start_date.strftime('%d.%m.%Y')
    if start_date.year == end_date.year:
        return f'{start_date.strftime("%d.%m")}–{end_date.strftime("%d.%m.%Y")}'
    return f'{start_date.strftime("%d.%m.%Y")}–{end_date.strftime("%d.%m.%Y")}'


def _birthday_date(year, day, month):
    last_day = month_calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _birthday_event(row, year, kind):
    if kind == 'player_birthday':
        day, month = row['day'], row['month']
        name = row['tag'] or 'Игрок'
        url = f'/users/{row["id"]}'
        subtitle = 'Игрок'
    else:
        day, month = row['birth_date'].day, row['birth_date'].month
        name = row['name']
        url = f'/characters/{row["id"]}'
        subtitle = f'Персонаж · {row["owner_tag"] or "Игрок"}'
    occurrence = _birthday_date(year, day, month)
    return {
        'id': f'{kind}-{row["id"]}', 'kind': kind, 'title': name,
        'subtitle': subtitle, 'description': '', 'url': url, 'external': False,
        'occurrence_date': occurrence, 'date_label': f'{day:02d}.{month:02d}',
    }


def build_calendar_page(year, month, game_code='', event_type='', today=None):
    games = list_games()
    if game_code and game_code not in {game['code'] for game in games}:
        raise ValueError('Игра не найдена')
    if event_type and event_type not in EVENT_TYPE_LABELS:
        raise ValueError('Неизвестный тип события')
    today = today or date.today()
    month_start = date(year, month, 1)
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    previous_month = date(year - (month == 1), 12 if month == 1 else month - 1, 1)

    game_event_type = event_type if event_type in {'event', 'banner'} else ''
    include_game_events = not event_type or event_type in {'event', 'banner'}
    game_events = list_calendar_events(
        month_start, next_month, game_code, game_event_type,
    ) if include_game_events else []
    players = list_player_birthdays() if event_type in {'', 'player_birthday'} else []
    characters = list_character_birthdays() if event_type in {'', 'character_birthday'} else []

    events_by_day = {}
    agenda = []
    for event in game_events:
        item = {
            'id': f'game-{event["id"]}', 'kind': event['event_type'], 'title': event['title'],
            'subtitle': event['game_name'], 'description': event['description'],
            'url': event['url'], 'external': True,
            'date_label': _date_range(event['start_date'], event['end_date']),
            'occurrence_date': max(event['start_date'], month_start),
        }
        agenda.append(item)
        occurrence = max(event['start_date'], month_start)
        last_occurrence = min(event['end_date'], next_month - timedelta(days=1))
        while occurrence <= last_occurrence:
            events_by_day.setdefault(occurrence, []).append(item)
            occurrence += timedelta(days=1)

    for kind, rows in (('player_birthday', players), ('character_birthday', characters)):
        for row in rows:
            item = _birthday_event(row, year, kind)
            if item['occurrence_date'].month != month:
                continue
            agenda.append(item)
            events_by_day.setdefault(item['occurrence_date'], []).append(item)

    weeks = []
    for week in month_calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        cells = []
        for day_number in week:
            if not day_number:
                cells.append(None)
                continue
            day = date(year, month, day_number)
            cells.append({
                'date': day, 'number': day_number, 'is_today': day == today,
                'events': events_by_day.get(day, []),
            })
        weeks.append(cells)

    kind_order = {kind: index for index, kind in enumerate(EVENT_TYPE_LABELS)}
    agenda.sort(key=lambda item: (
        item['occurrence_date'], kind_order[item['kind']], item['title'].casefold(),
    ))
    return {
        'games': games, 'selected_game': game_code, 'selected_type': event_type,
        'event_types': EVENT_TYPE_LABELS.items(), 'type_labels': EVENT_TYPE_LABELS,
        'weekdays': WEEKDAYS, 'weeks': weeks,
        'agenda': agenda, 'month_name': MONTH_NAMES[month], 'year': year,
        'month_value': f'{year:04d}-{month:02d}',
        'previous_url': _url(previous_month.year, previous_month.month, game_code, event_type),
        'next_url': _url(next_month.year, next_month.month, game_code, event_type),
        'today_url': _url(today.year, today.month, game_code, event_type),
        'active_page': 'calendar',
    }
