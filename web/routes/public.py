from math import ceil

from fastapi import APIRouter, HTTPException, Query, Request

from web.media import get_media_store
from web.queries import (
    count_characters, count_media, count_users, get_public_character,
    get_public_media, get_public_stats, get_public_user,
    get_public_user_characters, get_public_user_games, list_active_tags,
    list_characters, list_media, list_users,
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


@router.get('/media', name='media_catalog')
async def media_catalog(
    request: Request,
    tag: int | None = Query(None, ge=1),
    kind: str | None = None,
    sort: str = 'newest',
    page: int = Query(1, ge=1),
):
    if kind == '':
        kind = None
    try:
        items = list_media(tag_id=tag, kind=kind, sort=sort, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        total = count_media(tag_id=tag, kind=kind)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return templates.TemplateResponse(
        request=request,
        name='media_list.html',
        context={
            'items': items, 'tags': list_active_tags(), 'selected_tag': tag,
            'selected_kind': kind, 'selected_sort': sort,
            'pagination': _pagination(page, total), 'active_page': 'media',
        },
    )


@router.get('/users', name='users')
async def users(request: Request, page: int = Query(1, ge=1)):
    total = count_users()
    return templates.TemplateResponse(
        request=request,
        name='users.html',
        context={
            'users': list_users(limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE),
            'pagination': _pagination(page, total), 'active_page': 'users',
        },
    )


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
