from fastapi import APIRouter, Depends, Form, HTTPException, Request

from database.queries import get_user_by_tg_id
from database.wishes import (
    get_or_create_current_wish_event, get_participant, get_recent_drops,
    get_wish_participant_stats, list_wish_banners, list_wish_winners, perform_wishes,
)
from web.auth import csrf_protect, require_admin
from web.rendering import templates

router = APIRouter()


def _wish_page_context(session, banner_id=None):
    event = get_or_create_current_wish_event()
    banners = list_wish_banners(event['id'], active_only=True)
    if not banners:
        raise HTTPException(status_code=500, detail='В ивенте нет активных баннеров')
    selected = next((banner for banner in banners if banner['id'] == banner_id), banners[0])
    user = get_user_by_tg_id(session['tg_id'])
    participant = get_participant(event['id'], user['id'])
    return {
        'event': event, 'banners': banners, 'selected_banner': selected,
        'participant': participant, 'stats': get_wish_participant_stats(event['id']),
        'recent_drops': get_recent_drops(event['id'], user['id']),
        'winners': list_wish_winners(event['id']), 'csrf_token': session['csrf'],
        'active_page': 'admin_wishes',
    }


@router.get('/wishes', name='wishes_page')
async def wishes_page(
    request: Request, banner: int | None = None, session=Depends(require_admin),
):
    return templates.TemplateResponse(
        request=request, name='wish_page.html',
        context=_wish_page_context(session, banner),
    )


@router.post('/wishes/{event_id}/pull', name='wishes_pull')
async def wishes_pull(
    event_id: int,
    banner_id: int = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    user = get_user_by_tg_id(session['tg_id'])
    if not user:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    try:
        result = perform_wishes(event_id, user['id'], banner_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        'drops': result['drops'],
        'remaining': result['remaining'],
        'participant': get_participant(event_id, user['id']),
        'stats': get_wish_participant_stats(event_id),
    }
