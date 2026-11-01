from math import ceil

from fastapi import APIRouter, HTTPException, Query, Request

from web.media import get_media_store
from web.queries import (
    count_characters, count_media, count_users, get_public_character,
    get_public_media, get_public_stats, get_public_user,
    get_public_user_characters, get_public_user_games, get_user_avatar_data,
    list_active_tags, list_characters, list_media, list_users, update_user_avatar,
)
from web.rendering import templates

router = APIRouter()
PAGE_SIZE = 24


def _pagination(page, total, page_size=PAGE_SIZE):
    pages = max(ceil(total / page_size), 1)
    return {
        'page': page, 'pages': pages, 'total': total,
        'previous': page - 1 if page > 1 else None,
        'next': page + 1 if page < pages else None,
    }


@router.get('/', name='home')
async def home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='home.html',
        context={
            'stats': get_public_stats(),
            'latest_media': list_media(limit=6),
            'active_page': 'home',
        },
    )


def _parse_optional_date(value):
    from datetime import date

    return date.fromisoformat(value) if value else None


@router.get('/media', name='media_catalog')
async def media_catalog(
    request: Request,
    tag: str = '',
    kind: str = '',
    sort: str = 'newest',
    date_from: str = '',
    date_to: str = '',
    page: int = Query(1, ge=1),
):
    try:
        selected_tag = int(tag) if tag else None
        if selected_tag is not None and selected_tag < 1:
            raise ValueError('Некорректный тег')
        selected_date_from = _parse_optional_date(date_from)
        selected_date_to = _parse_optional_date(date_to)
        if selected_date_from and selected_date_to and selected_date_from > selected_date_to:
            raise ValueError('Дата начала не может быть позже даты окончания')
        selected_kind = kind or None
        items = list_media(
            tag_id=selected_tag, kind=selected_kind, sort=sort,
            date_from=selected_date_from, date_to=selected_date_to,
            limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE,
        )
        total = count_media(
            tag_id=selected_tag, kind=selected_kind,
            date_from=selected_date_from, date_to=selected_date_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name='media_list.html',
        context={
            'items': items, 'tags': list_active_tags(), 'selected_tag': selected_tag,
            'selected_kind': selected_kind, 'selected_sort': sort,
            'date_from': selected_date_from.isoformat() if selected_date_from else '',
            'date_to': selected_date_to.isoformat() if selected_date_to else '',
            'pagination': _pagination(page, total), 'active_page': 'media',
        },
    )


USERS_PAGE_SIZE = 12


def _user_page(page, search):
    from urllib.parse import urlencode

    search = search.strip()
    total = count_users(search)
    items = list_users(
        limit=USERS_PAGE_SIZE, offset=(page - 1) * USERS_PAGE_SIZE, search=search,
    )
    next_url = None
    if page * USERS_PAGE_SIZE < total:
        next_url = f'/users/fragment?{urlencode({"q": search, "page": page + 1})}'
    return items, total, next_url


@router.get('/users', name='users')
async def users(request: Request, q: str = '', page: int = Query(1, ge=1)):
    items, total, next_url = _user_page(page, q)
    return templates.TemplateResponse(
        request=request,
        name='users.html',
        context={
            'users': items, 'total': total, 'search': q.strip(),
            'page': page, 'next_url': next_url, 'has_more': next_url is not None,
            'active_page': 'users',
        },
    )


@router.get('/users/fragment', name='users_fragment')
async def users_fragment(q: str = '', page: int = Query(1, ge=1)):
    items, total, next_url = _user_page(page, q)
    return {
        'html': templates.get_template('_user_cards.html').render(users=items),
        'next_url': next_url,
        'total': total,
    }


@router.get('/users/{user_id}', name='user_detail')
async def user_detail(request: Request, user_id: int):
    user = get_public_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    return templates.TemplateResponse(
        request=request,
        name='user_detail.html',
        context={
            'user': user, 'games': get_public_user_games(user_id),
            'characters': get_public_user_characters(user_id), 'active_page': 'users',
        },
    )


@router.get('/characters', name='characters')
async def characters(request: Request, page: int = Query(1, ge=1)):
    total = count_characters()
    return templates.TemplateResponse(
        request=request,
        name='characters.html',
        context={
            'characters': list_characters(limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE),
            'pagination': _pagination(page, total), 'active_page': 'characters',
        },
    )


@router.get('/characters/{character_id}', name='character_detail')
async def character_detail(request: Request, character_id: int):
    character = get_public_character(character_id)
    if not character:
        raise HTTPException(status_code=404, detail='Персонаж не найден')
    return templates.TemplateResponse(
        request=request,
        name='character_detail.html',
        context={'character': character, 'active_page': 'characters'},
    )


@router.get('/media/files/{usage_id}', name='media_file')
async def media_file(usage_id: int):
    item = get_public_media(usage_id)
    if not item or not item['media_file_id']:
        raise HTTPException(status_code=404, detail='Файл не найден')
    return await get_media_store().get_response(item['media_file_id'], f'publication-{usage_id}')


@router.get('/media/characters/{character_id}', name='character_photo')
async def character_photo(character_id: int):
    character = get_public_character(character_id)
    if not character or not character['photo_file_id']:
        raise HTTPException(status_code=404, detail='Фото не найдено')
    return await get_media_store().get_response(
        character['photo_file_id'], f'character-{character_id}',
    )


@router.get('/media/users/{user_id}/avatar', name='user_avatar')
async def user_avatar(user_id: int):
    from datetime import datetime, timedelta, timezone

    avatar = get_user_avatar_data(user_id)
    if not avatar:
        raise HTTPException(status_code=404, detail='Игрок не найден')
    file_id = avatar['avatar_file_id']
    is_fresh = (
        avatar['avatar_updated_at']
        and datetime.now(timezone.utc) - avatar['avatar_updated_at'] < timedelta(hours=24)
    )
    if not file_id or not is_fresh:
        file_id = await get_media_store().get_profile_photo_file_id(avatar['tg_id'])
        if not file_id:
            raise HTTPException(status_code=404, detail='У игрока нет фото профиля')
        update_user_avatar(user_id, file_id)
    return await get_media_store().get_response(file_id, f'user-{user_id}-avatar')
