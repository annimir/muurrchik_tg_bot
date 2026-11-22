from datetime import date, timedelta
from urllib.parse import urlencode

from database.calendar import (
    list_calendar_events, list_character_birthdays, list_player_birthdays,
)
from web.calendar import (
    EVENT_TYPE_LABELS, WEEKDAYS, _birthday_event, _date_range, game_color,
)
from web.queries import list_games

MAX_TIMELINE_DAYS = 367


def _url(view, game_code, event_type, week=None, day=None, year=None, month=None):
    params = {'view': view}
    if week:
        params['week'] = week.isoformat()
    if day:
        params['day'] = day.isoformat()
    if year is not None and month is not None:
        params.update(year=year, month=month)
    if game_code:
        params['game'] = game_code
    if event_type:
        params['type'] = event_type
    return f'/calendar?{urlencode(params)}'


def _row(label, subtitle, events, range_start, range_end):
    bars = []
    lane_ends = []
    for event in sorted(
        events, key=lambda item: (item['start_date'], item['end_date'], item['title'].casefold()),
    ):
        bar_start = max(event['start_date'], range_start)
        bar_end = min(event['end_date'], range_end)
        start_index = (bar_start - range_start).days
        end_index = (bar_end - range_start).days
        lane = next(
            (index for index, end in enumerate(lane_ends) if end < start_index),
            len(lane_ends),
        )
        if lane == len(lane_ends):
            lane_ends.append(end_index)
        else:
            lane_ends[lane] = end_index
        bars.append({
            'id': event['id'], 'kind': event['kind'], 'title': event['title'],
            'subtitle': event['subtitle'], 'url': event['url'],
            'external': event['external'], 'column': start_index + 2,
            'span': end_index - start_index + 1, 'row': lane + 1,
            'date_label': event['date_label'], 'game_color': event.get('game_color'),
            'continues_before': event['start_date'] < range_start,
            'continues_after': event['end_date'] > range_end,
        })
    return {
        'label': label, 'subtitle': subtitle, 'bars': bars,
        'event_rows': len(lane_ends), 'event_count': len(events),
    }


def _birthdays(range_start, range_end, event_type):
    events = []
    sources = []
    if event_type in {'', 'player_birthday'}:
        sources.append(('player_birthday', list_player_birthdays()))
    if event_type in {'', 'character_birthday'}:
        sources.append(('character_birthday', list_character_birthdays()))
    for year in range(range_start.year, range_end.year + 1):
        for kind, rows in sources:
            for row in rows:
                item = _birthday_event(row, year, kind)
                occurrence = item['occurrence_date']
                if range_start <= occurrence <= range_end:
                    item.update(
                        start_date=occurrence, end_date=occurrence,
                        subtitle=item['subtitle'],
                    )
                    events.append(item)
    return events


def build_calendar_timeline(
    range_start, range_end, game_code='', event_type='', today=None, anchor_date=None,
):
    if range_end < range_start:
        raise ValueError('Дата окончания не может быть раньше даты начала')
    day_count = (range_end - range_start).days + 1
    if day_count > MAX_TIMELINE_DAYS:
        raise ValueError('За один раз можно загрузить не более 367 дней')
    games = list_games()
    if game_code and game_code not in {game['code'] for game in games}:
        raise ValueError('Игра не найдена')
    if event_type and event_type not in EVENT_TYPE_LABELS:
        raise ValueError('Неизвестный тип события')
    today = today or date.today()
    anchor_date = anchor_date or range_start

    game_event_type = event_type if event_type in {'event', 'banner'} else ''
    include_game_events = not event_type or event_type in {'event', 'banner'}
    game_events = list_calendar_events(
        range_start, range_end + timedelta(days=1), game_code, game_event_type,
    ) if include_game_events else []

    rows = []
    if event_type in {'', 'player_birthday', 'character_birthday'}:
        birthdays = _birthdays(range_start, range_end, event_type)
        rows.append(_row('Дни рождения', 'Игроки и персонажи', birthdays, range_start, range_end))

    visible_games = [
        game for game in games if not game_code or game['code'] == game_code
    ] if include_game_events else []
    for game in visible_games:
        related = [event for event in game_events if event['game_code'] == game['code']]
        color = game_color(game['code'])
        items = [{
            'id': f'game-{event["id"]}', 'kind': event['event_type'],
            'title': event['title'], 'subtitle': game['name'], 'url': event['url'],
            'external': True, 'start_date': event['start_date'], 'end_date': event['end_date'],
            'date_label': _date_range(event['start_date'], event['end_date']),
            'game_color': color,
        } for event in related]
        row = _row(game['name'], f'Событий: {len(items)}', items, range_start, range_end)
        row['game_code'] = game['code']
        row['game_color'] = color
        rows.append(row)

    days = []
    for index in range(day_count):
        day = range_start + timedelta(days=index)
        days.append({
            'date': day, 'number': day.day, 'weekday': WEEKDAYS[day.weekday()],
            'is_today': day == today, 'is_weekend': day.weekday() >= 5,
            'is_month_start': day.day == 1, 'is_anchor': day == anchor_date,
        })
    return {
        'games': games, 'selected_game': game_code, 'selected_type': event_type,
        'event_types': EVENT_TYPE_LABELS.items(), 'days': days, 'rows': rows,
        'day_count': day_count, 'range_start': range_start, 'range_end': range_end,
        'range_label': _date_range(range_start, range_end), 'anchor_date': anchor_date,
        'month_url': _url(
            'month', game_code, event_type, year=anchor_date.year, month=anchor_date.month,
        ),
        'current_week_url': _url('week', game_code, event_type),
        'current_day_url': _url('day', game_code, event_type),
        'active_page': 'calendar',
    }
