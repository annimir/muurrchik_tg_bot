from datetime import date, datetime, time, timedelta, timezone
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
from web.charts import build_daily_bars, build_line_chart, build_pie_chart
from web.queries import (
    add_admin_character_affiliation, add_admin_tag_alias, assign_character,
    create_admin_affiliation, create_character, create_role, delete_admin_affiliation,
    delete_admin_tag, delete_admin_tag_alias, delete_character, delete_role,
    get_admin_affiliation, get_admin_character, get_admin_overview, get_admin_player,
    get_admin_role, get_admin_tag, get_admin_tag_character_links, get_daily_analytics,
    get_recent_audit, get_tag_popularity_for_day, get_tag_subscription_popularity,
    get_tag_usage_bounds, get_tag_usage_series, list_admin_affiliations,
    list_admin_character_affiliations, list_admin_character_tag_links,
    list_admin_characters, list_admin_media, list_admin_players, list_admin_roles,
    list_admin_tags, list_admin_users, list_games, remove_admin_character_affiliation,
    set_media_visibility, update_admin_affiliation, update_admin_player,
    update_admin_tag_status, update_character, update_role,
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


TAG_USAGE_PERIODS = (
    ('all', 'За весь период'),
    ('hour', 'За час'),
    ('day', 'За день'),
    ('week', 'За неделю'),
    ('two_weeks', 'За две недели'),
    ('custom', 'Выбранный период'),
)
TAG_USAGE_PERIOD_LABELS = dict(TAG_USAGE_PERIODS)


def _resolve_tag_usage_period(period, date_from=None, date_to=None):
    if period not in TAG_USAGE_PERIOD_LABELS:
        raise ValueError('Неизвестный период статистики')
    now = datetime.now(timezone.utc)
    if period == 'custom':
        if not date_from or not date_to:
            raise ValueError('Укажите даты начала и окончания периода')
        if date_from > date_to:
            raise ValueError('Дата начала не может быть позже даты окончания')
        start = datetime.combine(date_from, time.min, tzinfo=timezone.utc)
        end = datetime.combine(date_to + timedelta(days=1), time.min, tzinfo=timezone.utc)
    elif period == 'all':
        first_usage = get_tag_usage_bounds()['first']
        start = first_usage or now - timedelta(days=14)
        end = now
    else:
        duration = {
            'hour': timedelta(hours=1),
            'day': timedelta(days=1),
            'week': timedelta(days=7),
            'two_weeks': timedelta(days=14),
        }[period]
        start = now - duration
        end = now

    duration = end - start
    if period == 'hour':
        interval, label_format = '5 minutes', '%H:%M'
    elif duration <= timedelta(days=2):
        interval, label_format = '1 hour', '%d.%m %H:%M'
    elif duration <= timedelta(days=60):
        interval, label_format = '1 day', '%d.%m'
    else:
        interval, label_format = '1 month', '%m.%Y'
    return {'start': start, 'end': end, 'interval': interval, 'label_format': label_format}


def _tag_usage_context(period, date_from='', date_to=''):
    selected_date_from = date.fromisoformat(date_from) if date_from else None
    selected_date_to = date.fromisoformat(date_to) if date_to else None
    usage_period = _resolve_tag_usage_period(period, selected_date_from, selected_date_to)
    usage_rows = get_tag_usage_series(
        usage_period['start'], usage_period['end'], usage_period['interval'],
    )
    return {
        'chart': build_line_chart(usage_rows, label_format=usage_period['label_format']),
        'period_options': TAG_USAGE_PERIODS, 'selected_period': period,
        'selected_period_label': TAG_USAGE_PERIOD_LABELS[period],
        'date_from': selected_date_from.isoformat() if selected_date_from else '',
        'date_to': selected_date_to.isoformat() if selected_date_to else '',
    }


@router.get('/tag-usage/fragment', name='admin_tag_usage_fragment')
async def tag_usage_fragment(
    period: str = 'two_weeks',
    date_from: str = '',
    date_to: str = '',
    _=Depends(require_admin),
):
    try:
        context = _tag_usage_context(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'html': templates.get_template('admin/_tag_usage_chart.html').render(**context)}


@router.get('', name='admin_dashboard')
async def dashboard(
    request: Request,
    day: date | None = None,
    period: str = 'two_weeks',
    date_from: str = '',
    date_to: str = '',
    session=Depends(require_admin),
):
    selected_day = day or date.today()
    try:
        usage_context = _tag_usage_context(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    analytics = get_daily_analytics(selected_day)
    return templates.TemplateResponse(
        request=request,
        name='admin/dashboard.html',
        context={
            'overview': get_admin_overview(), 'analytics': analytics,
            'daily_bars': build_daily_bars(analytics), 'selected_day': selected_day,
            'popular_tags': get_tag_popularity_for_day(selected_day),
            'rare_tags': get_tag_popularity_for_day(selected_day, rare=True),
            'subscription_chart': build_pie_chart(get_tag_subscription_popularity()),
            **usage_context,
            'audit': get_recent_audit(), 'csrf_token': session['csrf'],
            'active_page': 'dashboard',
        },
    )


def _parse_player_birthday(value):
    value = value.strip()
    if not value:
        return None
    try:
        if '.' in value:
            day_text, month_text = value.split('.')
            birthday = {'day': int(day_text), 'month': int(month_text), 'year': None}
            date(2000, birthday['month'], birthday['day'])
        else:
            parsed = date.fromisoformat(value)
            birthday = {'day': parsed.day, 'month': parsed.month, 'year': parsed.year}
    except (TypeError, ValueError):
        raise ValueError('Укажите дату в формате ДД.ММ или ГГГГ-ММ-ДД') from None
    if birthday['year'] and date(birthday['year'], birthday['month'], birthday['day']) > date.today():
        raise ValueError('Дата рождения не может быть в будущем')
    return birthday


@router.get('/players', name='admin_players')
async def players(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request,
        name='admin/players.html',
        context={
            'players': list_admin_players(), 'csrf_token': session['csrf'],
            'active_page': 'admin_players',
        },
    )


def _player_edit_context(session, player, error=None, birthday_input=None):
    return {
        'player': player, 'games': list_games(), 'birthday_input': birthday_input,
        'csrf_token': session['csrf'], 'active_page': 'admin_players', 'error': error,
    }


@router.get('/players/{user_id}/edit', name='admin_edit_player')
async def edit_player(request: Request, user_id: int, session=Depends(require_admin)):
    player = get_admin_player(user_id)
    if not player:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    return templates.TemplateResponse(
        request=request, name='admin/player_edit.html',
        context=_player_edit_context(session, player),
    )


@router.post('/players/{user_id}/edit', name='admin_update_player')
async def update_player_action(
    request: Request,
    user_id: int,
    bio: str = Form(''),
    birthday: str = Form(''),
    games: list[str] = Form(default=[]),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    player = get_admin_player(user_id)
    if not player:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    bio = bio.strip()
    try:
        if len(bio) > MAX_TEXT_LENGTH:
            raise ValueError(f'Информация не должна превышать {MAX_TEXT_LENGTH} символов')
        parsed_birthday = _parse_player_birthday(birthday)
        update_admin_player(session['tg_id'], user_id, bio, parsed_birthday, games)
    except ValueError as exc:
        submitted_player = {**player, 'bio': bio, 'game_codes': games}
        return templates.TemplateResponse(
            request=request, name='admin/player_edit.html',
            context=_player_edit_context(session, submitted_player, str(exc), birthday),
            status_code=400,
        )
    return RedirectResponse('/admin/players', status_code=303)


def _tags_context(session, error=None, q='', status='', character_q=''):
    return {
        'tags': list_admin_tags(q, status),
        'tag_options': list_admin_tags(status='ACTIVE'),
        'characters': list_admin_character_tag_links(character_q),
        'search': q.strip(), 'selected_status': status,
        'character_search': character_q.strip(),
        'status_options': {'ACTIVE': 'Активен', 'DELETED': 'Удалён', 'BLOCKED': 'Заблокирован'},
        'csrf_token': session['csrf'], 'active_page': 'admin_tags', 'error': error,
    }


@router.get('/tags', name='admin_tags')
async def admin_tags(
    request: Request,
    q: str = '',
    status: str = '',
    character_q: str = '',
    session=Depends(require_admin),
):
    try:
        context = _tags_context(session, q=q, status=status, character_q=character_q)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request, name='admin/tags.html', context=context,
    )


def _tag_detail_context(session, tag, error=None):
    return {
        'tag': tag, 'character_links': get_admin_tag_character_links(tag['id']),
        'status_options': {'ACTIVE': 'Активен', 'DELETED': 'Удалён', 'BLOCKED': 'Заблокирован'},
        'csrf_token': session['csrf'], 'active_page': 'admin_tags', 'error': error,
    }


@router.get('/tags/{tag_id}', name='admin_tag_detail')
async def admin_tag_detail(request: Request, tag_id: int, session=Depends(require_admin)):
    tag = get_admin_tag(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail='Тег не найден')
    return templates.TemplateResponse(
        request=request, name='admin/tag_detail.html', context=_tag_detail_context(session, tag),
    )


@router.post('/tags/{tag_id}/status', name='admin_update_tag_status')
async def update_tag_status_action(
    request: Request,
    tag_id: int,
    status: str = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    tag = get_admin_tag(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail='Тег не найден')
    try:
        update_admin_tag_status(session['tg_id'], tag_id, status)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/tag_detail.html',
            context=_tag_detail_context(session, tag, str(exc)), status_code=400,
        )
    return RedirectResponse(f'/admin/tags/{tag_id}', status_code=303)


@router.post('/tags/{tag_id}/delete', name='admin_delete_tag')
async def delete_tag_action(
    request: Request,
    tag_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_admin_tag(session['tg_id'], tag_id)
    except ValueError as exc:
        tag = get_admin_tag(tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail='Тег не найден') from exc
        return templates.TemplateResponse(
            request=request, name='admin/tag_detail.html',
            context=_tag_detail_context(session, tag, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/tags', status_code=303)


@router.post('/tags/{tag_id}/aliases/{alias_id}/delete', name='admin_delete_tag_alias_from_detail')
async def delete_tag_alias_from_detail_action(
    request: Request,
    tag_id: int,
    alias_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    tag = get_admin_tag(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail='Тег не найден')
    try:
        delete_admin_tag_alias(session['tg_id'], alias_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/tag_detail.html',
            context=_tag_detail_context(session, tag, str(exc)), status_code=400,
        )
    return RedirectResponse(f'/admin/tags/{tag_id}', status_code=303)


@router.post('/tags/aliases', name='admin_create_tag_alias')
async def create_tag_alias_action(
    request: Request,
    tag_id: int = Form(...),
    alias: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    alias = alias.strip()
    try:
        if not 1 <= len(alias) <= MAX_NAME_LENGTH:
            raise ValueError(f'Алиас должен содержать от 1 до {MAX_NAME_LENGTH} символов')
        add_admin_tag_alias(session['tg_id'], tag_id, alias)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/tags.html',
            context=_tags_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/tags', status_code=303)


@router.post('/tags/aliases/{alias_id}/delete', name='admin_delete_tag_alias')
async def delete_tag_alias_action(
    request: Request,
    alias_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_admin_tag_alias(session['tg_id'], alias_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/tags.html',
            context=_tags_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/tags', status_code=303)


@router.post('/tags/characters', name='admin_assign_character_tag')
async def assign_character_tag_action(
    request: Request,
    character_id: int = Form(...),
    tag_id: int = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        add_admin_tag_alias(session['tg_id'], tag_id, '', character_id=character_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/tags.html',
            context=_tags_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/tags', status_code=303)


def _affiliations_context(session, error=None, q='', character_q=''):
    return {
        'affiliations': list_admin_affiliations(q),
        'affiliation_options': list_admin_affiliations(),
        'characters': list_admin_character_affiliations(character_q),
        'search': q.strip(), 'character_search': character_q.strip(),
        'csrf_token': session['csrf'], 'active_page': 'admin_affiliations', 'error': error,
    }


@router.get('/affiliations', name='admin_affiliations')
async def admin_affiliations(
    request: Request, q: str = '', character_q: str = '', session=Depends(require_admin),
):
    return templates.TemplateResponse(
        request=request, name='admin/affiliations.html',
        context=_affiliations_context(session, q=q, character_q=character_q),
    )


@router.post('/affiliations', name='admin_create_affiliation')
async def create_affiliation_action(
    request: Request,
    name: str = Form(...),
    parent_id: int | None = Form(None),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        create_admin_affiliation(session['tg_id'], name, parent_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/affiliations.html',
            context=_affiliations_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/affiliations', status_code=303)


def _affiliation_edit_context(session, affiliation, error=None):
    return {
        'affiliation': affiliation, 'affiliation_options': list_admin_affiliations(),
        'csrf_token': session['csrf'], 'active_page': 'admin_affiliations', 'error': error,
    }


@router.get('/affiliations/{affiliation_id}/edit', name='admin_edit_affiliation')
async def edit_affiliation(
    request: Request, affiliation_id: int, session=Depends(require_admin),
):
    affiliation = get_admin_affiliation(affiliation_id)
    if not affiliation:
        raise HTTPException(status_code=404, detail='Принадлежность не найдена')
    return templates.TemplateResponse(
        request=request, name='admin/affiliation_edit.html',
        context=_affiliation_edit_context(session, affiliation),
    )


@router.post('/affiliations/{affiliation_id}/edit', name='admin_update_affiliation')
async def update_affiliation_action(
    request: Request,
    affiliation_id: int,
    name: str = Form(...),
    parent_id: int | None = Form(None),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    affiliation = get_admin_affiliation(affiliation_id)
    if not affiliation:
        raise HTTPException(status_code=404, detail='Принадлежность не найдена')
    name = name.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        update_admin_affiliation(session['tg_id'], affiliation_id, name, parent_id)
    except ValueError as exc:
        submitted = {**affiliation, 'name': name, 'parent_id': parent_id}
        return templates.TemplateResponse(
            request=request, name='admin/affiliation_edit.html',
            context=_affiliation_edit_context(session, submitted, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/affiliations', status_code=303)


@router.post('/affiliations/{affiliation_id}/delete', name='admin_delete_affiliation')
async def delete_affiliation_action(
    request: Request,
    affiliation_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_admin_affiliation(session['tg_id'], affiliation_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/affiliations.html',
            context=_affiliations_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/affiliations', status_code=303)


@router.post('/affiliations/characters', name='admin_assign_character_affiliation')
async def assign_character_affiliation_action(
    request: Request,
    character_id: int = Form(...),
    affiliation_id: int = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        add_admin_character_affiliation(session['tg_id'], character_id, affiliation_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/affiliations.html',
            context=_affiliations_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/affiliations', status_code=303)


@router.post(
    '/affiliations/characters/{character_id}/{affiliation_id}/delete',
    name='admin_remove_character_affiliation',
)
async def remove_character_affiliation_action(
    request: Request,
    character_id: int,
    affiliation_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        remove_admin_character_affiliation(session['tg_id'], character_id, affiliation_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/affiliations.html',
            context=_affiliations_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/affiliations', status_code=303)


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


def _character_edit_context(session, character, error=None):
    return {
        'character': character, 'csrf_token': session['csrf'],
        'active_page': 'admin_characters', 'error': error,
    }


@router.get('/characters/{character_id}/edit', name='admin_edit_character')
async def edit_character(request: Request, character_id: int, session=Depends(require_admin)):
    character = get_admin_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail='Персонаж не найден')
    return templates.TemplateResponse(
        request=request, name='admin/character_edit.html',
        context=_character_edit_context(session, character),
    )


@router.post('/characters/{character_id}/edit', name='admin_update_character')
async def update_character_action(
    request: Request,
    character_id: int,
    name: str = Form(...),
    birth_date: str = Form(''),
    description: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    character = get_admin_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail='Персонаж не найден')
    name = name.strip()
    description = description.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Имя должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        if len(description) > MAX_TEXT_LENGTH:
            raise ValueError(f'Описание не должно превышать {MAX_TEXT_LENGTH} символов')
        parsed_birth_date = date.fromisoformat(birth_date) if birth_date else None
        update_character(session['tg_id'], character_id, name, parsed_birth_date, description or None)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/character_edit.html',
            context=_character_edit_context(session, character, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/characters', status_code=303)


@router.post('/characters/{character_id}/delete', name='admin_delete_character')
async def delete_character_action(
    character_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_character(session['tg_id'], character_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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


def _role_edit_context(session, role, error=None):
    return {
        'role': role, 'csrf_token': session['csrf'],
        'active_page': 'admin_roles', 'error': error,
    }


@router.get('/roles/{role_id}/edit', name='admin_edit_role')
async def edit_role(request: Request, role_id: int, session=Depends(require_admin)):
    role = get_admin_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail='Роль не найдена')
    return templates.TemplateResponse(
        request=request, name='admin/role_edit.html',
        context=_role_edit_context(session, role),
    )


@router.post('/roles/{role_id}/edit', name='admin_update_role')
async def update_role_action(
    request: Request,
    role_id: int,
    name: str = Form(...),
    description: str = Form(''),
    wiki_url: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    role = get_admin_role(role_id)
    if not role:
        raise HTTPException(status_code=404, detail='Роль не найдена')
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
        update_role(session['tg_id'], role_id, name, description or None, wiki_url or None)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/role_edit.html',
            context=_role_edit_context(session, role, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/roles', status_code=303)


@router.post('/roles/{role_id}/delete', name='admin_delete_role')
async def delete_role_action(
    role_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_role(session['tg_id'], role_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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
