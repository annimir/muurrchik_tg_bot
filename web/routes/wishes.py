from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from config.config import config
from database.queries import ensure_user, get_all_admin_ids, get_user_by_tg_id
from database.wishes import (
    get_or_create_current_wish_event, get_participant, get_recent_drops,
    get_wish_participant_stats, list_wish_banners, list_wish_winners, perform_wishes,
)
from database.wish_rewards import (
    get_wish_reward_progress, get_wish_reward_summary, list_wish_reward_grants,
)
from web.auth import (
    SESSION_COOKIE, create_admin_session, csrf_protect, read_admin_session, require_user,
    verify_telegram_login,
)
from web.rendering import templates

router = APIRouter()


def _wish_page_context(session, banner_id=None):
    event = get_or_create_current_wish_event()
    banners = list_wish_banners(event['id'], active_only=True)
    if not banners:
        raise HTTPException(status_code=500, detail='В ивенте нет активных баннеров')
    selected = next((banner for banner in banners if banner['id'] == banner_id), banners[0])
    user = get_user_by_tg_id(session['tg_id'])
    if not user:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    is_admin = session['tg_id'] in get_all_admin_ids()
    participant = get_participant(event['id'], user['id'])
    return {
        'event': event, 'banners': banners, 'selected_banner': selected,
        'participant': participant, 'stats': get_wish_participant_stats(event['id']),
        'recent_drops': get_recent_drops(event['id'], user['id']),
        'winners': list_wish_winners(event['id']), 'csrf_token': session['csrf'],
        'reward_rules': get_wish_reward_progress(event['id'], user['id']),
        'reward_summary': get_wish_reward_summary(event['id'], user['id']),
        'reward_grants': list_wish_reward_grants(event['id'], user['id'], limit=10),
        'user': user, 'is_admin': is_admin,
        'active_page': 'admin_wishes' if is_admin else 'wishes',
    }


@router.get('/wishes/login', name='wishes_login')
async def wishes_login(request: Request):
    if read_admin_session(request):
        return RedirectResponse('/wishes', status_code=303)
    return templates.TemplateResponse(
        request=request,
        name='wish_login.html',
        context={
            'bot_username': config.web_telegram_bot_username,
            'auth_url': f'{config.web_public_base_url}/wishes/login/telegram',
            'active_page': 'wishes',
        },
    )


@router.get('/wishes/login/telegram', name='wishes_login_telegram')
async def wishes_login_telegram(request: Request):
    if not verify_telegram_login(request.query_params, config.bot_token):
        raise HTTPException(status_code=403, detail='Не удалось подтвердить вход через Telegram')
    tg_id = int(request.query_params['id'])
    user = get_user_by_tg_id(tg_id)
    if not user:
        full_name = ' '.join(filter(None, (
            request.query_params.get('first_name', '').strip(),
            request.query_params.get('last_name', '').strip(),
        )))
        tag = request.query_params.get('username') or full_name or str(tg_id)
        ensure_user(tg_id, tag)
    token, _ = create_admin_session(tg_id)
    response = RedirectResponse('/wishes', status_code=303)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=config.web_session_ttl_seconds,
        httponly=True, secure=config.web_secure_cookies, samesite='lax', path='/',
    )
    return response


@router.post('/wishes/logout', name='wishes_logout')
async def wishes_logout(_=Depends(require_user), __=Depends(csrf_protect)):
    response = RedirectResponse('/wishes/login', status_code=303)
    response.delete_cookie(SESSION_COOKIE, path='/')
    return response


@router.get('/wishes', name='wishes_page')
async def wishes_page(
    request: Request, banner: int | None = None, session=Depends(require_user),
):
    return templates.TemplateResponse(
        request=request, name='wish_page.html',
        context=_wish_page_context(session, banner),
    )


@router.post('/wishes/{event_id}/pull', name='wishes_pull')
async def wishes_pull(
    event_id: int,
    banner_id: int = Form(...),
    count: int = Form(10),
    session=Depends(require_user),
    _=Depends(csrf_protect),
):
    user = get_user_by_tg_id(session['tg_id'])
    if not user:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    try:
        result = perform_wishes(event_id, user['id'], banner_id, count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        'drops': result['drops'],
        'remaining': result['remaining'],
        'rewards': result['rewards'],
        'participant': get_participant(event_id, user['id']),
        'stats': get_wish_participant_stats(event_id),
        'reward_rules': get_wish_reward_progress(event_id, user['id']),
        'reward_summary': get_wish_reward_summary(event_id, user['id']),
    }
