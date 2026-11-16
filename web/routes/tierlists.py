import json

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from config.config import config
from database.queries import ensure_user, get_user_by_tg_id
from database.tierlists import (
    TierListConflictError,
    attach_tier_list_previews,
    create_tier_list,
    delete_tier_list,
    get_tier_list,
    list_public_tier_lists,
    list_user_tier_lists,
    update_tier_list,
)
from services.tierlist_catalog import (
    RANKED_TIER_CODES,
    get_tierlist_filter_options,
    list_tierlist_characters,
    tierlist_game_codes,
)
from web.auth import (
    SESSION_COOKIE,
    create_admin_session,
    csrf_protect,
    read_admin_session,
    verify_telegram_login,
)
from web.queries import list_games
from web.rendering import templates

router = APIRouter()
TIER_LABELS = {
    'S': 'S', 'A': 'A', 'B': 'B', 'C': 'C', 'D': 'D', 'UNRANKED': 'Без тира',
}


def _require_tierlist_user(request: Request):
    session = read_admin_session(request)
    if not session:
        raise HTTPException(status_code=303, headers={'Location': '/tierlists/login'})
    return session


def _session_user(session):
    user = get_user_by_tg_id(session['tg_id'])
    if not user:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    return user


def _available_games():
    available = set(tierlist_game_codes())
    return [game for game in list_games() if game['code'] in available]


def _rows(tier_list, ranked_only=False):
    characters = {
        character['id']: character
        for character in list_tierlist_characters(tier_list['game_codes'])
    }
    rows = {tier: [] for tier in (*RANKED_TIER_CODES, 'UNRANKED')}
    for entry in tier_list['entries']:
        character = characters.get(entry['character_id'])
        if character:
            rows[entry['tier']].append(character)
    if ranked_only:
        rows.pop('UNRANKED')
    return rows


def _editor_context(tier_list, csrf_token):
    return {
        'tier_list': tier_list,
        'rows': _rows(tier_list),
        'tiers': RANKED_TIER_CODES,
        'tier_labels': TIER_LABELS,
        'filter_options': get_tierlist_filter_options(tier_list['game_codes']),
        'games': _available_games(),
        'csrf_token': csrf_token,
        'active_page': 'tierlists',
    }


@router.get('/tierlists/login', name='tierlists_login')
async def tierlists_login(request: Request):
    if read_admin_session(request):
        return RedirectResponse('/tierlists/mine', status_code=303)
    return templates.TemplateResponse(
        request=request,
        name='tierlist_login.html',
        context={
            'bot_username': config.web_telegram_bot_username,
            'auth_url': f'{config.web_public_base_url}/tierlists/login/telegram',
            'active_page': 'tierlists',
        },
    )


@router.get('/tierlists/login/telegram', name='tierlists_login_telegram')
async def tierlists_login_telegram(request: Request):
    if not verify_telegram_login(request.query_params, config.bot_token):
        raise HTTPException(status_code=403, detail='Не удалось подтвердить вход через Telegram')
    tg_id = int(request.query_params['id'])
    if not get_user_by_tg_id(tg_id):
        full_name = ' '.join(filter(None, (
            request.query_params.get('first_name', '').strip(),
            request.query_params.get('last_name', '').strip(),
        )))
        tag = request.query_params.get('username') or full_name or str(tg_id)
        ensure_user(tg_id, tag)
    token, _ = create_admin_session(tg_id)
    response = RedirectResponse('/tierlists/mine', status_code=303)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=config.web_session_ttl_seconds,
        httponly=True, secure=config.web_secure_cookies, samesite='lax', path='/',
    )
    return response


@router.get('/tierlists', name='tierlists_page')
async def tierlists_page(request: Request, player: list[int] = Query(default=[])):
    all_tier_lists = list_public_tier_lists()
    players_by_id = {
        tier_list['owner_id']: {
            'id': tier_list['owner_id'], 'tag': tier_list['owner_tag'],
        }
        for tier_list in all_tier_lists
    }
    selected_player_ids = sorted(set(player) & set(players_by_id))
    selected_players = set(selected_player_ids)
    tier_lists = [
        tier_list for tier_list in all_tier_lists
        if not selected_players or tier_list['owner_id'] in selected_players
    ]
    player_filter_label = ', '.join(
        players_by_id[player_id]['tag'] or 'Игрок' for player_id in selected_player_ids
    ) or 'Все игроки'
    return templates.TemplateResponse(
        request=request,
        name='tierlists.html',
        context={
            'tier_lists': attach_tier_list_previews(tier_lists),
            'players': sorted(
                players_by_id.values(), key=lambda player: (player['tag'] or '').lower(),
            ),
            'selected_player_ids': selected_player_ids,
            'player_filter_label': player_filter_label,
            'is_authenticated': read_admin_session(request) is not None,
            'public_view': True,
            'active_page': 'tierlists',
        },
    )


@router.get('/tierlists/mine', name='tierlists_mine')
async def tierlists_mine(request: Request, session=Depends(_require_tierlist_user)):
    user = _session_user(session)
    return templates.TemplateResponse(
        request=request,
        name='tierlists.html',
        context={
            'tier_lists': attach_tier_list_previews(list_user_tier_lists(user['id'])),
            'user': user,
            'public_view': False,
            'active_page': 'tierlists',
        },
    )


@router.get('/tierlists/new', name='tierlist_new')
async def tierlist_new(request: Request, session=Depends(_require_tierlist_user)):
    user = _session_user(session)
    user_games = set(getattr(user, 'game_codes', []) or [])
    if not user_games:
        from database.queries import get_user_games
        user_games = get_user_games(user['id'])
    return templates.TemplateResponse(
        request=request,
        name='tierlist_new.html',
        context={
            'games': _available_games(),
            'selected_games': user_games,
            'csrf_token': session['csrf'],
            'active_page': 'tierlists',
        },
    )


@router.post('/tierlists', name='tierlist_create')
async def tierlist_create(
    title: str = Form(...),
    games: list[str] = Form(default=[]),
    session=Depends(_require_tierlist_user),
    _=Depends(csrf_protect),
):
    user = _session_user(session)
    try:
        tier_list = create_tier_list(user['id'], title, games)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f'/tierlists/{tier_list["id"]}/edit', status_code=303)


@router.get('/tierlists/{tier_list_id}/edit', name='tierlist_edit')
async def tierlist_edit(
    request: Request, tier_list_id: int, session=Depends(_require_tierlist_user),
):
    user = _session_user(session)
    tier_list = get_tier_list(tier_list_id, user['id'])
    if not tier_list:
        raise HTTPException(status_code=404, detail='Тирлист не найден')
    return templates.TemplateResponse(
        request=request,
        name='tierlist_editor.html',
        context=_editor_context(tier_list, session['csrf']),
    )


@router.post('/tierlists/{tier_list_id}', name='tierlist_update')
async def tierlist_update(
    tier_list_id: int,
    title: str = Form(...),
    games: list[str] = Form(default=[]),
    entries: str = Form(...),
    version: int = Form(...),
    session=Depends(_require_tierlist_user),
    _=Depends(csrf_protect),
):
    user = _session_user(session)
    if not get_tier_list(tier_list_id, user['id']):
        raise HTTPException(status_code=404, detail='Тирлист не найден')
    try:
        parsed_entries = json.loads(entries)
        if not isinstance(parsed_entries, list):
            raise ValueError('Некорректная раскладка')
        tier_list = update_tier_list(
            user['id'], tier_list_id, title, games, parsed_entries, version,
        )
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail='Некорректная раскладка') from exc
    except TierListConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {'ok': True, 'version': tier_list['lock_version']}


@router.post('/tierlists/{tier_list_id}/delete', name='tierlist_delete')
async def tierlist_delete(
    tier_list_id: int,
    session=Depends(_require_tierlist_user),
    _=Depends(csrf_protect),
):
    user = _session_user(session)
    if not delete_tier_list(user['id'], tier_list_id):
        raise HTTPException(status_code=404, detail='Тирлист не найден')
    return RedirectResponse('/tierlists/mine', status_code=303)


@router.get('/tierlists/{tier_list_id}', name='tierlist_detail')
async def tierlist_detail(request: Request, tier_list_id: int):
    tier_list = get_tier_list(tier_list_id)
    if not tier_list:
        raise HTTPException(status_code=404, detail='Тирлист не найден')
    return templates.TemplateResponse(
        request=request,
        name='tierlist_detail.html',
        context={
            'tier_list': tier_list,
            'rows': _rows(tier_list, ranked_only=True),
            'tiers': RANKED_TIER_CODES,
            'tier_labels': TIER_LABELS,
            'filter_options': get_tierlist_filter_options(tier_list['game_codes']),
            'games': _available_games(),
            'active_page': 'tierlists',
        },
    )
