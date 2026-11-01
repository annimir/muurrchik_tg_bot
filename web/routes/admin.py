from datetime import date
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from config.config import config
from database.queries import get_all_admin_ids
from services.validation import MAX_NAME_LENGTH, MAX_TEXT_LENGTH
from web.auth import (
    SESSION_COOKIE, create_admin_session, csrf_protect, read_admin_session,
    require_admin, verify_telegram_login,
)
from web.charts import build_daily_bars, build_line_chart
from web.queries import (
    assign_character, create_character, create_role, get_admin_overview,
    get_daily_analytics, get_recent_audit, get_tag_daily_series,
    get_tag_popularity_for_day, list_admin_characters, list_admin_media,
    list_admin_roles, list_admin_users, set_media_visibility,
)
from web.rendering import templates

router = APIRouter(prefix='/admin')


@router.get('/login', name='admin_login')
async def login(request: Request):
    if read_admin_session(request):
        return RedirectResponse('/admin', status_code=303)
    return templates.TemplateResponse(
        request=request,
        name='admin/login.html',
        context={
            'bot_username': config.web_telegram_bot_username,
            'auth_url': f'{config.web_public_base_url}/admin/login/telegram',
            'active_page': None,
        },
    )


@router.get('/login/telegram', name='admin_login_telegram')
async def login_telegram(request: Request):
    if not verify_telegram_login(request.query_params, config.bot_token):
        raise HTTPException(status_code=403, detail='Не удалось подтвердить вход через Telegram')
    tg_id = int(request.query_params['id'])
    if tg_id not in get_all_admin_ids():
        raise HTTPException(status_code=403, detail='Эта учётная запись не является администратором')
    token, _ = create_admin_session(tg_id)
    response = RedirectResponse('/admin', status_code=303)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=config.web_session_ttl_seconds,
        httponly=True, secure=config.web_secure_cookies, samesite='lax', path='/',
    )
    return response


@router.post('/logout', name='admin_logout')
async def logout(_=Depends(require_admin), __=Depends(csrf_protect)):
    response = RedirectResponse('/admin/login', status_code=303)
    response.delete_cookie(SESSION_COOKIE, path='/')
    return response


@router.get('', name='admin_dashboard')
async def dashboard(request: Request, day: date | None = None, session=Depends(require_admin)):
    selected_day = day or date.today()
    analytics = get_daily_analytics(selected_day)
    return templates.TemplateResponse(
        request=request,
        name='admin/dashboard.html',
        context={
            'overview': get_admin_overview(), 'analytics': analytics,
            'daily_bars': build_daily_bars(analytics), 'selected_day': selected_day,
            'popular_tags': get_tag_popularity_for_day(selected_day),
            'rare_tags': get_tag_popularity_for_day(selected_day, rare=True),
            'chart': build_line_chart(get_tag_daily_series()),
            'audit': get_recent_audit(), 'csrf_token': session['csrf'],
            'active_page': 'dashboard',
        },
    )


def _characters_context(session, error=None):
    return {
        'characters': list_admin_characters(), 'users': list_admin_users(),
        'csrf_token': session['csrf'], 'active_page': 'admin_characters',
        'error': error,
    }


@router.get('/characters', name='admin_characters')
async def characters(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request, name='admin/characters.html', context=_characters_context(session),
    )


@router.post('/characters', name='admin_create_character')
async def create_character_action(
    request: Request,
    owner_user_id: int = Form(...),
    name: str = Form(...),
    birth_date: str = Form(''),
    description: str = Form(''),
    is_primary: bool = Form(False),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    description = description.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Имя должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        if len(description) > MAX_TEXT_LENGTH:
            raise ValueError(f'Описание не должно превышать {MAX_TEXT_LENGTH} символов')
        parsed_birth_date = date.fromisoformat(birth_date) if birth_date else None
        create_character(
            session['tg_id'], owner_user_id, name, parsed_birth_date,
            description or None, is_primary,
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/characters.html',
            context=_characters_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/characters', status_code=303)


@router.post('/characters/{character_id}/assign', name='admin_assign_character')
async def assign_character_action(
    request: Request,
    character_id: int,
    owner_user_id: int = Form(...),
    is_primary: bool = Form(False),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        assign_character(session['tg_id'], character_id, owner_user_id, is_primary)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/characters.html',
            context=_characters_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/characters', status_code=303)


@router.get('/roles', name='admin_roles')
async def roles(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request,
        name='admin/roles.html',
        context={
            'roles': list_admin_roles(), 'csrf_token': session['csrf'],
            'active_page': 'admin_roles', 'error': None,
        },
    )


@router.post('/roles', name='admin_create_role')
async def create_role_action(
    request: Request,
    name: str = Form(...),
    description: str = Form(''),
    wiki_url: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    description = description.strip()
    wiki_url = wiki_url.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        if len(description) > MAX_TEXT_LENGTH:
            raise ValueError(f'Описание не должно превышать {MAX_TEXT_LENGTH} символов')
        if wiki_url and (urlparse(wiki_url).scheme not in {'http', 'https'} or len(wiki_url) > 2048):
            raise ValueError('Укажите корректную ссылку HTTP или HTTPS')
        create_role(session['tg_id'], name, description or None, wiki_url or None)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name='admin/roles.html',
            context={
                'roles': list_admin_roles(), 'csrf_token': session['csrf'],
                'active_page': 'admin_roles', 'error': str(exc),
            },
            status_code=400,
        )
    return RedirectResponse('/admin/roles', status_code=303)


@router.get('/media', name='admin_media')
async def media(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request,
        name='admin/media.html',
        context={
            'items': list_admin_media(), 'csrf_token': session['csrf'],
            'active_page': 'admin_media',
        },
    )


@router.post('/media/{usage_id}/visibility', name='admin_media_visibility')
async def media_visibility(
    usage_id: int,
    is_public: bool = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        set_media_visibility(session['tg_id'], usage_id, is_public)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return RedirectResponse('/admin/media', status_code=303)
