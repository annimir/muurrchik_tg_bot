from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from database.calendar import (
    create_calendar_event, delete_calendar_event, get_calendar_event,
    list_admin_calendar_events, update_calendar_event,
)
from web.auth import csrf_protect, require_admin
from web.calendar import build_calendar_page
from web.calendar_timeline import build_calendar_timeline
from web.queries import list_games
from web.rendering import templates

router = APIRouter()


@router.get('/calendar', name='calendar_page')
async def calendar_page(
    request: Request, year: int | None = None, month: int | None = None,
    game: str = '', type: str = '', month_value: str = '', view: str = 'month',
    week: str = '', day: str = '',
):
    today = date.today()
    selected_game = game.strip()
    selected_type = type.strip()
    if view in {'week', 'day'}:
        try:
            if view == 'week':
                anchor = date.fromisoformat(week) if week else today
                anchor -= timedelta(days=anchor.weekday())
                range_start = anchor - timedelta(days=7)
                range_end = anchor + timedelta(days=13)
            else:
                anchor = date.fromisoformat(day) if day else today
                range_start = anchor - timedelta(days=7)
                range_end = anchor + timedelta(days=7)
            context = build_calendar_timeline(
                range_start, range_end, selected_game, selected_type,
                today=today, anchor_date=anchor,
            )
            context.update(
                view_mode=view,
                view_title='Недельная лента' if view == 'week' else 'Дневная лента',
                current_period_url=(
                    context['current_week_url'] if view == 'week' else context['current_day_url']
                ),
                current_period_label='Текущая неделя' if view == 'week' else 'Текущий день',
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return templates.TemplateResponse(
            request=request, name='calendar_timeline.html', context=context,
        )
    if view != 'month':
        raise HTTPException(status_code=400, detail='Неизвестный режим календаря')
    if month_value:
        try:
            year_text, month_text = month_value.split('-')
            year, month = int(year_text), int(month_text)
        except ValueError:
            raise HTTPException(status_code=400, detail='Некорректный месяц') from None
    if year is None:
        year = today.year
    if month is None:
        month = today.month
    if not 1 <= month <= 12:
        raise HTTPException(status_code=400, detail='Месяц должен быть от 1 до 12')
    try:
        context = build_calendar_page(year, month, selected_game, selected_type, today=today)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    day_value = f'{year:04d}-{month:02d}-01'
    week_params = {'view': 'week', 'week': day_value}
    day_params = {'view': 'day', 'day': day_value}
    for params in (week_params, day_params):
        if selected_game:
            params['game'] = selected_game
        if selected_type:
            params['type'] = selected_type
    context['week_url'] = f'/calendar?{urlencode(week_params)}'
    context['day_url'] = f'/calendar?{urlencode(day_params)}'
    return templates.TemplateResponse(request=request, name='calendar.html', context=context)


@router.get('/calendar/timeline', name='calendar_timeline_fragment')
async def calendar_timeline_fragment(
    start: date, end: date, game: str = '', type: str = '',
):
    try:
        context = build_calendar_timeline(start, end, game.strip(), type.strip())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        'html': templates.get_template('_calendar_timeline.html').render(**context),
        'start': start.isoformat(), 'end': end.isoformat(),
        'range_label': context['range_label'], 'category_count': len(context['rows']),
    }


def _admin_context(session, event=None, error=None):
    today = date.today()
    event = event or {
        'title': '', 'description': '', 'game_code': '', 'event_type': 'event',
        'start_date': today, 'end_date': today, 'url': '',
    }
    return {
        'event': event, 'events': list_admin_calendar_events(), 'games': list_games(),
        'editing': bool(event.get('id')), 'csrf_token': session['csrf'],
        'active_page': 'admin_calendar', 'error': error,
    }


def _submitted_event(
    title, description, game_code, event_type, start_date, end_date, url, event_id=None,
):
    return {
        'id': event_id, 'title': title, 'description': description, 'game_code': game_code,
        'event_type': event_type, 'start_date': start_date, 'end_date': end_date, 'url': url,
    }


@router.get('/admin/calendar', name='admin_calendar')
async def admin_calendar(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request, name='admin/calendar.html', context=_admin_context(session),
    )


@router.post('/admin/calendar', name='admin_calendar_create')
async def admin_calendar_create(
    request: Request, title: str = Form(...), description: str = Form(''),
    game_code: str = Form(...), event_type: str = Form(...),
    start_date: str = Form(...), end_date: str = Form(...), url: str = Form(''),
    session=Depends(require_admin), _=Depends(csrf_protect),
):
    event = _submitted_event(
        title, description, game_code, event_type, start_date, end_date, url,
    )
    try:
        create_calendar_event(
            session['tg_id'], game_code, title, description, event_type,
            start_date, end_date, url,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/calendar.html',
            context=_admin_context(session, event, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/calendar', status_code=303)


@router.get('/admin/calendar/{event_id}/edit', name='admin_calendar_edit')
async def admin_calendar_edit(request: Request, event_id: int, session=Depends(require_admin)):
    event = get_calendar_event(event_id)
    if not event:
        raise HTTPException(status_code=404, detail='Событие не найдено')
    return templates.TemplateResponse(
        request=request, name='admin/calendar.html', context=_admin_context(session, event),
    )


@router.post('/admin/calendar/{event_id}/edit', name='admin_calendar_update')
async def admin_calendar_update(
    request: Request, event_id: int, title: str = Form(...), description: str = Form(''),
    game_code: str = Form(...), event_type: str = Form(...),
    start_date: str = Form(...), end_date: str = Form(...), url: str = Form(''),
    session=Depends(require_admin), _=Depends(csrf_protect),
):
    event = _submitted_event(
        title, description, game_code, event_type, start_date, end_date, url, event_id,
    )
    try:
        update_calendar_event(
            session['tg_id'], event_id, game_code, title, description, event_type,
            start_date, end_date, url,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/calendar.html',
            context=_admin_context(session, event, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/calendar', status_code=303)


@router.post('/admin/calendar/{event_id}/delete', name='admin_calendar_delete')
async def admin_calendar_delete(
    event_id: int, session=Depends(require_admin), _=Depends(csrf_protect),
):
    try:
        delete_calendar_event(session['tg_id'], event_id)
    except ValueError:
        pass
    return RedirectResponse('/admin/calendar', status_code=303)
