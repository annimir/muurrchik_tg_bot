from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from psycopg2 import IntegrityError

from database.calendar_activity import (
    create_activity_cycle, delete_activity_cycle, get_activity_cycle,
    list_admin_activity_cycles, list_calendar_activities, update_activity_cycle,
)
from services.tierlist_catalog import get_tierlist_filter_options, list_tierlist_characters
from web.auth import csrf_protect, require_admin
from web.calendar_activity import build_cycle_details
from web.rendering import templates

router = APIRouter()


def _context(session, cycle=None, error=None):
    today = date.today()
    cycle = cycle or {
        'activity_id': '', 'start_date': '', 'end_date': '', 'cycle_month': today.strftime('%Y-%m'),
        'patch_start': '', 'details': {},
    }
    characters = [
        character for character in list_tierlist_characters(['genshin'])
        if character.get('availability', 'playable') == 'playable'
    ]
    return {
        'cycle': cycle, 'cycles': list_admin_activity_cycles(),
        'activities': list_calendar_activities(), 'characters': characters,
        'elements': get_tierlist_filter_options(['genshin'])['element'],
        'editing': bool(cycle.get('id')), 'error': error, 'csrf_token': session['csrf'],
        'active_page': 'admin_calendar_cycles',
    }


def _submitted(activity_id, details, cycle_month, patch_start, start_date, end_date, cycle_id=None):
    return {
        'id': cycle_id, 'activity_id': activity_id, 'details': details,
        'cycle_month': cycle_month, 'patch_start': patch_start,
        'start_date': start_date, 'end_date': end_date,
    }


def _details(boss1, boss2, boss3, elements, invited_characters, first_half, second_half):
    return {
        'bosses': [boss1, boss2, boss3], 'elements': elements,
        'invited_characters': invited_characters,
        'first_half': first_half, 'second_half': second_half,
    }


@router.get('/calendar/cycles/{cycle_id}', name='calendar_cycle_details')
async def cycle_details(cycle_id: int):
    cycle = get_activity_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail='Цикл не найден')
    details = build_cycle_details(cycle)
    return {
        'title': details['title'],
        'html': templates.get_template('_calendar_cycle_details.html').render(**details),
    }


@router.get('/admin/calendar/cycles', name='admin_calendar_cycles')
async def admin_cycles(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request, name='admin/calendar_cycles.html', context=_context(session),
    )


@router.post('/admin/calendar/cycles', name='admin_calendar_cycle_create')
async def admin_cycle_create(
    request: Request, activity_id: int = Form(...), cycle_month: str = Form(''),
    patch_start: str = Form(''), start_date: str = Form(''), end_date: str = Form(''),
    boss1: str = Form(''), boss2: str = Form(''), boss3: str = Form(''),
    elements: list[str] = Form(default=[]), invited_characters: list[str] = Form(default=[]),
    first_half: str = Form(''), second_half: str = Form(''),
    session=Depends(require_admin), _=Depends(csrf_protect),
):
    details = _details(boss1, boss2, boss3, elements, invited_characters, first_half, second_half)
    cycle = _submitted(activity_id, details, cycle_month, patch_start, start_date, end_date)
    try:
        create_activity_cycle(
            session['tg_id'], activity_id, details,
            cycle_month, patch_start, start_date, end_date,
        )
    except (ValueError, IntegrityError) as exc:
        message = 'Такой цикл уже существует' if isinstance(exc, IntegrityError) else str(exc)
        return templates.TemplateResponse(
            request=request, name='admin/calendar_cycles.html',
            context=_context(session, cycle, message), status_code=400,
        )
    return RedirectResponse('/admin/calendar/cycles', status_code=303)


@router.get('/admin/calendar/cycles/{cycle_id}/edit', name='admin_calendar_cycle_edit')
async def admin_cycle_edit(request: Request, cycle_id: int, session=Depends(require_admin)):
    cycle = get_activity_cycle(cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail='Цикл не найден')
    cycle['cycle_month'] = cycle['start_date'].strftime('%Y-%m')
    cycle['patch_start'] = ''
    return templates.TemplateResponse(
        request=request, name='admin/calendar_cycles.html', context=_context(session, cycle),
    )


@router.post('/admin/calendar/cycles/{cycle_id}/edit', name='admin_calendar_cycle_update')
async def admin_cycle_update(
    request: Request, cycle_id: int, activity_id: int = Form(...), cycle_month: str = Form(''),
    patch_start: str = Form(''), start_date: str = Form(''), end_date: str = Form(''),
    boss1: str = Form(''), boss2: str = Form(''), boss3: str = Form(''),
    elements: list[str] = Form(default=[]), invited_characters: list[str] = Form(default=[]),
    first_half: str = Form(''), second_half: str = Form(''),
    session=Depends(require_admin), _=Depends(csrf_protect),
):
    details = _details(boss1, boss2, boss3, elements, invited_characters, first_half, second_half)
    cycle = _submitted(activity_id, details, cycle_month, patch_start, start_date, end_date, cycle_id)
    try:
        update_activity_cycle(
            session['tg_id'], cycle_id, activity_id, details,
            cycle_month, patch_start, start_date, end_date,
        )
    except (ValueError, IntegrityError) as exc:
        message = 'Такой цикл уже существует' if isinstance(exc, IntegrityError) else str(exc)
        return templates.TemplateResponse(
            request=request, name='admin/calendar_cycles.html',
            context=_context(session, cycle, message), status_code=400,
        )
    return RedirectResponse('/admin/calendar/cycles', status_code=303)


@router.post('/admin/calendar/cycles/{cycle_id}/delete', name='admin_calendar_cycle_delete')
async def admin_cycle_delete(
    cycle_id: int, session=Depends(require_admin), _=Depends(csrf_protect),
):
    delete_activity_cycle(session['tg_id'], cycle_id)
    return RedirectResponse('/admin/calendar/cycles', status_code=303)
