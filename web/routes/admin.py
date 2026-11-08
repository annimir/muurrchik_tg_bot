from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse

from config.config import config
from database.assistance import (
    admin_cancel_help_request, create_game_mode, list_admin_game_modes,
    list_admin_helpers, list_admin_help_requests, set_game_mode_active,
    set_helper_admin_active,
)
from database.queries import get_all_admin_ids, get_all_positions, get_user_titles
from database.wishes import (
    add_wish_item, calculate_wish_winners, create_wish_banner, delete_wish_item,
    get_or_create_current_wish_event, get_wish_participant_stats, list_wish_banners,
    list_wish_events, list_wish_items, list_wish_winners, restart_wish_event,
    set_wish_allowance, set_wish_banner_active,
)
from database.wish_rewards import (
    list_wish_reward_grants, list_wish_reward_rules, update_wish_reward_rule,
)
from services.games import slugify_game_name
from services.validation import MAX_NAME_LENGTH, MAX_TEXT_LENGTH
from web.auth import (
    SESSION_COOKIE, create_admin_session, csrf_protect, read_admin_session,
    require_admin, verify_telegram_login,
)
from web.charts import build_daily_bars, build_line_chart, build_pie_chart
from web.queries import (
    ConcurrentEditError,
    add_admin_character_affiliation, add_admin_tag_alias, add_admin_user_title,
    assign_character, create_admin_affiliation, create_admin_game, create_admin_position,
    create_character, delete_admin_affiliation, delete_admin_game, delete_admin_position,
    delete_admin_tag, delete_admin_tag_alias,
    delete_admin_user_title, delete_character, get_admin_affiliation, get_admin_character,
    get_admin_overview, get_admin_player, get_admin_tag, get_admin_tag_character_links,
    get_daily_analytics, get_public_user_characters, get_recent_audit,
    get_tag_popularity_for_day, get_tag_subscription_popularity, get_tag_usage_bounds,
    get_tag_usage_series, list_admin_affiliations, list_admin_character_affiliations,
    list_admin_character_tag_links, list_admin_characters, list_admin_games, list_admin_media,
    list_admin_players, list_admin_tags, list_admin_users, list_games,
    remove_admin_character_affiliation, set_media_visibility, update_admin_affiliation,
    update_admin_player, update_admin_position, update_admin_tag_status, update_character,
)
from web.media import get_media_store
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


def _parse_character_birthday(value):
    value = value.strip()
    if not value:
        return None
    try:
        day_text, month_text = value.split('.')
        return date(2000, int(month_text), int(day_text))
    except (TypeError, ValueError):
        raise ValueError('Укажите день рождения в формате ДД.ММ') from None


def _parse_player_birthday(value):
    parsed = _parse_character_birthday(value)
    if not parsed:
        return None
    return {'day': parsed.day, 'month': parsed.month, 'year': None}


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
        'player': player, 'games': list_games(), 'titles': get_user_titles(player['id']),
        'characters': get_public_user_characters(player['id']), 'birthday_input': birthday_input,
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
    chat_position: str = Form(''),
    games: list[str] = Form(default=[]),
    version: int = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    player = get_admin_player(user_id)
    if not player:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    bio = bio.strip()
    chat_position = chat_position.strip()
    try:
        if len(bio) > MAX_TEXT_LENGTH:
            raise ValueError(f'Информация не должна превышать {MAX_TEXT_LENGTH} символов')
        if len(chat_position) > MAX_NAME_LENGTH:
            raise ValueError(f'Должность не должна превышать {MAX_NAME_LENGTH} символов')
        parsed_birthday = _parse_player_birthday(birthday)
        update_admin_player(
            session['tg_id'], user_id, bio, parsed_birthday, games, chat_position, version,
        )
    except ValueError as exc:
        current_player = get_admin_player(user_id) or player
        submitted_player = {
            **current_player, 'bio': bio, 'game_codes': games, 'chat_position': chat_position,
        }
        return templates.TemplateResponse(
            request=request, name='admin/player_edit.html',
            context=_player_edit_context(session, submitted_player, str(exc), birthday),
            status_code=409 if isinstance(exc, ConcurrentEditError) else 400,
        )
    return RedirectResponse('/admin/players', status_code=303)


@router.post('/players/{user_id}/titles', name='admin_add_user_title')
async def add_user_title_action(
    request: Request,
    user_id: int,
    name: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    player = get_admin_player(user_id)
    if not player:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    name = name.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Титул должен содержать от 1 до {MAX_NAME_LENGTH} символов')
        add_admin_user_title(session['tg_id'], user_id, name)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/player_edit.html',
            context=_player_edit_context(session, player, str(exc)), status_code=400,
        )
    return RedirectResponse(f'/admin/players/{user_id}/edit', status_code=303)


@router.post('/players/{user_id}/titles/{title_id}/delete', name='admin_delete_user_title')
async def delete_user_title_action(
    request: Request,
    user_id: int,
    title_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    player = get_admin_player(user_id)
    if not player:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    try:
        delete_admin_user_title(session['tg_id'], user_id, title_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/player_edit.html',
            context=_player_edit_context(session, player, str(exc)), status_code=400,
        )
    return RedirectResponse(f'/admin/players/{user_id}/edit', status_code=303)


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


def _optional_position_id(value):
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise ValueError('Выбрана неизвестная должность') from None


def _characters_context(session, error=None):
    return {
        'characters': list_admin_characters(), 'users': list_admin_users(),
        'positions': get_all_positions(), 'csrf_token': session['csrf'],
        'active_page': 'admin_characters', 'error': error,
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
    position_id: str = Form(''),
    wiki_url: str = Form(''),
    is_primary: bool = Form(False),
    photo: UploadFile | None = File(None),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    description = description.strip()
    wiki_url = wiki_url.strip()
    saved_photo = None
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Имя должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        if len(description) > MAX_TEXT_LENGTH:
            raise ValueError(f'Описание не должно превышать {MAX_TEXT_LENGTH} символов')
        if wiki_url and (urlparse(wiki_url).scheme not in {'http', 'https'} or len(wiki_url) > 2048):
            raise ValueError('Укажите корректную ссылку HTTP или HTTPS')
        if photo and photo.filename:
            saved_photo = await get_media_store().save_upload(photo)
        create_character(
            session['tg_id'], owner_user_id, name, _parse_character_birthday(birth_date),
            description or None, is_primary, _optional_position_id(position_id),
            wiki_url or None, saved_photo,
        )
    except ValueError as exc:
        if saved_photo:
            get_media_store().delete_local(saved_photo)
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


def _character_edit_context(session, character, error=None, birth_date_input=None):
    return {
        'character': character, 'positions': get_all_positions(), 'csrf_token': session['csrf'],
        'active_page': 'admin_characters', 'error': error, 'birth_date_input': birth_date_input,
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
    wiki_url: str = Form(''),
    position_id: str = Form(''),
    version: int = Form(...),
    photo: UploadFile | None = File(None),
    remove_photo: bool = Form(False),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    character = get_admin_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail='Персонаж не найден')
    name = name.strip()
    description = description.strip()
    wiki_url = wiki_url.strip()
    saved_photo = None
    parsed_position_id = position_id
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Имя должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        if len(description) > MAX_TEXT_LENGTH:
            raise ValueError(f'Описание не должно превышать {MAX_TEXT_LENGTH} символов')
        if wiki_url and (urlparse(wiki_url).scheme not in {'http', 'https'} or len(wiki_url) > 2048):
            raise ValueError('Укажите корректную ссылку HTTP или HTTPS')
        parsed_position_id = _optional_position_id(position_id)
        new_photo = character['photo_file_id']
        if remove_photo:
            new_photo = None
        elif photo and photo.filename:
            saved_photo = await get_media_store().save_upload(photo)
            new_photo = saved_photo
        update_character(
            session['tg_id'], character_id, name, _parse_character_birthday(birth_date),
            description or None, wiki_url or None, parsed_position_id, version, new_photo,
        )
        if new_photo != character['photo_file_id']:
            get_media_store().delete_local(character['photo_file_id'])
    except ValueError as exc:
        if saved_photo:
            get_media_store().delete_local(saved_photo)
        current_character = get_admin_character(character_id) or character
        submitted_character = {
            **current_character, 'name': name, 'description': description,
            'wiki_url': wiki_url, 'position_id': parsed_position_id,
        }
        return templates.TemplateResponse(
            request=request, name='admin/character_edit.html',
            context=_character_edit_context(session, submitted_character, str(exc), birth_date),
            status_code=409 if isinstance(exc, ConcurrentEditError) else 400,
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


@router.post('/positions', name='admin_create_position')
async def create_position_action(
    request: Request,
    name: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        create_admin_position(session['tg_id'], name)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/characters.html',
            context=_characters_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/characters', status_code=303)


@router.post('/positions/{position_id}/edit', name='admin_update_position')
async def update_position_action(
    request: Request,
    position_id: int,
    name: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        update_admin_position(session['tg_id'], position_id, name)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/characters.html',
            context=_characters_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/characters', status_code=303)


@router.post('/positions/{position_id}/delete', name='admin_delete_position')
async def delete_position_action(
    request: Request,
    position_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_admin_position(session['tg_id'], position_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/characters.html',
            context=_characters_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/characters', status_code=303)


@router.get('/games', name='admin_games')
async def games(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request,
        name='admin/games.html',
        context={
            'games': list_admin_games(), 'csrf_token': session['csrf'],
            'active_page': 'admin_games', 'error': None,
        },
    )


@router.post('/games', name='admin_create_game')
async def create_game_action(
    request: Request,
    name: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    error = None
    status_code = 200
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        create_admin_game(session['tg_id'], name, slugify_game_name(name))
    except ValueError as exc:
        error = str(exc)
        status_code = 400
    if error is None:
        return RedirectResponse('/admin/games', status_code=303)
    return templates.TemplateResponse(
        request=request, name='admin/games.html',
        context={
            'games': list_admin_games(), 'csrf_token': session['csrf'],
            'active_page': 'admin_games', 'error': error,
        },
        status_code=status_code,
    )


@router.post('/games/{code}/delete', name='admin_delete_game')
async def delete_game_action(
    request: Request,
    code: str,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_admin_game(session['tg_id'], code)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/games.html',
            context={
                'games': list_admin_games(), 'csrf_token': session['csrf'],
                'active_page': 'admin_games', 'error': str(exc),
            },
            status_code=404,
        )
    return RedirectResponse('/admin/games', status_code=303)


def _wishes_admin_context(session, error=None, banner_id=None):
    event = get_or_create_current_wish_event()
    banners = list_wish_banners(event['id'])
    selected = next((banner for banner in banners if banner['id'] == banner_id), banners[0])
    return {
        'event': event, 'banners': banners, 'selected_banner': selected,
        'items': list_wish_items(selected['id']), 'stats': get_wish_participant_stats(event['id']),
        'winners': list_wish_winners(event['id']), 'events': list_wish_events(),
        'reward_rules': list_wish_reward_rules(),
        'reward_grants': list_wish_reward_grants(event['id']),
        'csrf_token': session['csrf'], 'active_page': 'admin_wishes', 'error': error,
    }


def _wishes_admin_error(request, session, exc, status_code=400):
    return templates.TemplateResponse(
        request=request, name='admin/wishes.html',
        context=_wishes_admin_context(session, str(exc)), status_code=status_code,
    )


@router.get('/wishes', name='admin_wishes')
async def wishes_admin(request: Request, banner: int | None = None, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request, name='admin/wishes.html',
        context=_wishes_admin_context(session, banner_id=banner),
    )


@router.post('/wishes/allowance', name='admin_wish_allowance')
async def wish_allowance_action(
    request: Request,
    allowance: int = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        if allowance < 10 or allowance % 10:
            raise ValueError('Лимит должен быть положительным и кратным 10')
        event = get_or_create_current_wish_event()
        set_wish_allowance(session['tg_id'], event['id'], allowance)
    except ValueError as exc:
        return _wishes_admin_error(request, session, exc)
    return RedirectResponse('/admin/wishes', status_code=303)


@router.post('/wishes/rewards/{code}', name='admin_update_wish_reward')
async def wish_reward_rule_action(
    request: Request,
    code: str,
    reward: int = Form(...),
    threshold: int = Form(...),
    daily_limit: str = Form(''),
    monthly_limit: str = Form(''),
    is_active: bool = Form(False),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        update_wish_reward_rule(
            session['tg_id'], code, reward, threshold,
            int(daily_limit) if daily_limit.strip() else None,
            int(monthly_limit) if monthly_limit.strip() else None,
            is_active,
        )
    except ValueError as exc:
        return _wishes_admin_error(request, session, exc)
    return RedirectResponse('/admin/wishes', status_code=303)


@router.post('/wishes/restart', name='admin_wish_restart')
async def wish_restart_action(request: Request, session=Depends(require_admin), _=Depends(csrf_protect)):
    try:
        event = get_or_create_current_wish_event()
        restart_wish_event(session['tg_id'], event['id'])
    except ValueError as exc:
        return _wishes_admin_error(request, session, exc)
    return RedirectResponse('/admin/wishes', status_code=303)


@router.post('/wishes/banners', name='admin_create_wish_banner')
async def wish_banner_create_action(
    request: Request,
    name: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        event = get_or_create_current_wish_event()
        create_wish_banner(session['tg_id'], event['id'], name)
    except ValueError as exc:
        return _wishes_admin_error(request, session, exc)
    return RedirectResponse('/admin/wishes', status_code=303)


@router.post('/wishes/banners/{banner_id}/active', name='admin_toggle_wish_banner')
async def wish_banner_active_action(
    request: Request,
    banner_id: int,
    active: bool = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        set_wish_banner_active(session['tg_id'], banner_id, active)
    except ValueError as exc:
        return _wishes_admin_error(request, session, exc, 404)
    return RedirectResponse('/admin/wishes', status_code=303)


@router.post('/wishes/items', name='admin_create_wish_item')
async def wish_item_create_action(
    request: Request,
    banner_id: int = Form(...),
    name: str = Form(''),
    rarity: int = Form(...),
    item_type: str = Form(...),
    display_name: str = Form(''),
    image_url: str = Form(''),
    featured: bool = Form(False),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    display_name = display_name.strip()
    image_url = image_url.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        if rarity not in {3, 4, 5} or item_type not in {'character', 'weapon'}:
            raise ValueError('Неизвестный тип предмета')
        if image_url and not image_url.startswith('/static/'):
            raise ValueError('Изображение должно находиться в /static/')
        add_wish_item(
            session['tg_id'], banner_id, name, rarity, item_type, featured,
            image_url or None, display_name or None,
        )
    except ValueError as exc:
        return _wishes_admin_error(request, session, exc)
    return RedirectResponse('/admin/wishes', status_code=303)


@router.post('/wishes/items/{item_id}/delete', name='admin_delete_wish_item')
async def wish_item_delete_action(
    request: Request,
    item_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_wish_item(session['tg_id'], item_id)
    except ValueError as exc:
        return _wishes_admin_error(request, session, exc, 404)
    return RedirectResponse('/admin/wishes', status_code=303)


@router.post('/wishes/winners', name='admin_calculate_wish_winners')
async def wish_winners_action(request: Request, session=Depends(require_admin), _=Depends(csrf_protect)):
    try:
        event = get_or_create_current_wish_event()
        if not calculate_wish_winners(event['id']):
            raise ValueError('Нет участников, использовавших все молитвы')
    except ValueError as exc:
        return _wishes_admin_error(request, session, exc)
    return RedirectResponse('/admin/wishes', status_code=303)


ASSISTANCE_STATUS_LABELS = {
    'OPEN': 'Ожидает ответов',
    'SCHEDULING': 'Выбор времени',
    'CONFIRMING': 'Ожидает подтверждения',
    'ASSIGNED': 'Назначена',
    'COMPLETED': 'Завершена',
    'CANCELLED': 'Отменена',
    'REJECTED': 'Все отказались',
    'NO_HELPERS': 'Нет помогаторов',
    'EXPIRED': 'Истекла',
}


def _assistance_context(session, error=None, selected_status='', selected_game=''):
    return {
        'games': list_games(), 'modes': list_admin_game_modes(),
        'helpers': list_admin_helpers(),
        'requests': list_admin_help_requests(selected_status, selected_game),
        'status_labels': ASSISTANCE_STATUS_LABELS,
        'active_statuses': ('OPEN', 'SCHEDULING', 'CONFIRMING', 'ASSIGNED'),
        'selected_status': selected_status, 'selected_game': selected_game,
        'csrf_token': session['csrf'], 'active_page': 'admin_assistance', 'error': error,
    }


@router.get('/assistance', name='admin_assistance')
async def assistance(
    request: Request, status: str = '', game: str = '', session=Depends(require_admin),
):
    if status and status not in ASSISTANCE_STATUS_LABELS:
        raise HTTPException(status_code=400, detail='Неизвестный статус заявки')
    return templates.TemplateResponse(
        request=request, name='admin/assistance.html',
        context=_assistance_context(session, selected_status=status, selected_game=game),
    )


@router.post('/assistance/modes', name='admin_create_assistance_mode')
async def create_assistance_mode_action(
    request: Request,
    game_code: str = Form(...),
    name: str = Form(''),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    name = name.strip()
    try:
        if not 1 <= len(name) <= MAX_NAME_LENGTH:
            raise ValueError(f'Название должно содержать от 1 до {MAX_NAME_LENGTH} символов')
        create_game_mode(session['tg_id'], game_code, name)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/assistance.html',
            context=_assistance_context(session, str(exc)), status_code=400,
        )
    return RedirectResponse('/admin/assistance', status_code=303)


@router.post('/assistance/modes/{mode_id}/active', name='admin_toggle_assistance_mode')
async def toggle_assistance_mode_action(
    request: Request,
    mode_id: int,
    active: bool = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        set_game_mode_active(session['tg_id'], mode_id, active)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/assistance.html',
            context=_assistance_context(session, str(exc)), status_code=404,
        )
    return RedirectResponse('/admin/assistance', status_code=303)


@router.post('/assistance/helpers/{user_id}/active', name='admin_toggle_helper')
async def toggle_helper_action(
    request: Request,
    user_id: int,
    active: bool = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        set_helper_admin_active(session['tg_id'], user_id, active)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/assistance.html',
            context=_assistance_context(session, str(exc)), status_code=404,
        )
    return RedirectResponse('/admin/assistance', status_code=303)


@router.post('/assistance/requests/{request_id}/cancel', name='admin_cancel_assistance')
async def cancel_assistance_action(
    request: Request,
    request_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        admin_cancel_help_request(session['tg_id'], request_id)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request, name='admin/assistance.html',
            context=_assistance_context(session, str(exc)), status_code=404,
        )
    return RedirectResponse('/admin/assistance', status_code=303)


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
