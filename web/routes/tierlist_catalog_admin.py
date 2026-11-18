import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from services import tierlist_catalog as catalog
from web.auth import csrf_protect, require_admin
from web.media import get_media_store
from web.queries import list_games
from web.rendering import templates

router = APIRouter(prefix='/admin/tierlist-catalog')
NEW_CHARACTER = {
    'id': 'new_character',
    'name': 'Новый персонаж',
    'game': 'genshin',
    'region': {'id': 'unknown', 'name': 'Неизвестно'},
    'element': {'id': 'unknown', 'name': 'Неизвестно'},
    'gender': {'id': 'unknown', 'name': 'Неизвестно'},
    'rarity': 5,
    'release': None,
    'image': '',
    'availability': 'playable',
    'affiliations': [],
}


def _catalog_context(session, q='', game='', error=None):
    characters = catalog.list_tierlist_characters()
    normalized_query = q.strip().casefold()
    filtered = [
        character for character in characters
        if (not game or character['game'] == game)
        and (
            not normalized_query
            or normalized_query in character['name'].casefold()
            or normalized_query in character['id'].casefold()
        )
    ]
    return {
        'characters': filtered,
        'total_count': len(characters),
        'games': list_games(),
        'search': q.strip(),
        'selected_game': game,
        'csrf_token': session['csrf'],
        'active_page': 'admin_tierlist_catalog',
        'error': error,
    }


def _editor_context(
    session, character_json, character_id='', version=None, error=None, image='', is_new=False,
):
    return {
        'character_json': character_json,
        'character_id': character_id,
        'version': version,
        'image': image,
        'is_new': is_new,
        'games': list_games(),
        'csrf_token': session['csrf'],
        'active_page': 'admin_tierlist_catalog',
        'error': error,
    }


def _json_context(session, characters_json, version, error=None):
    return {
        'characters_json': characters_json,
        'version': version,
        'csrf_token': session['csrf'],
        'active_page': 'admin_tierlist_catalog',
        'error': error,
    }


def _local_file_id(image):
    if image.startswith('/media/tierlists/'):
        return f'local:{image.removeprefix("/media/tierlists/")}'
    return None


def _cleanup_images(images, remaining_images):
    for image in set(images) - set(remaining_images):
        file_id = _local_file_id(image)
        if file_id:
            get_media_store().delete_local(file_id)


async def _apply_upload(payload, photo):
    if not photo or not photo.filename:
        return None
    saved = await get_media_store().save_upload(photo)
    payload['image'] = f'/media/tierlists/{saved.removeprefix("local:")}'
    return saved


@router.get('', name='admin_tierlist_catalog')
async def tierlist_catalog_page(
    request: Request, q: str = '', game: str = '', session=Depends(require_admin),
):
    return templates.TemplateResponse(
        request=request,
        name='admin/tierlist_catalog.html',
        context=_catalog_context(session, q, game),
    )


@router.get('/json', name='admin_tierlist_catalog_json')
async def tierlist_catalog_json_page(
    request: Request, download: bool = False, session=Depends(require_admin),
):
    characters = catalog.list_tierlist_characters()
    content = catalog.tierlist_catalog_json(characters)
    if download:
        return Response(
            content=content,
            media_type='application/json',
            headers={'Content-Disposition': 'attachment; filename="tierlist_characters.json"'},
        )
    return templates.TemplateResponse(
        request=request,
        name='admin/tierlist_catalog_json.html',
        context=_json_context(session, content, catalog.tierlist_catalog_version(characters)),
    )


@router.post('/json', name='admin_tierlist_catalog_json_save')
async def tierlist_catalog_json_save(
    request: Request,
    characters_json: str = Form(...),
    version: str = Form(...),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        payload = json.loads(characters_json)
        previous_characters = catalog.list_tierlist_characters()
        characters = catalog.save_tierlist_catalog(session['tg_id'], payload, version)
        _cleanup_images(
            [character['image'] for character in previous_characters],
            [character['image'] for character in characters],
        )
    except json.JSONDecodeError as exc:
        error = f'Ошибка JSON: строка {exc.lineno}, колонка {exc.colno}: {exc.msg}'
        status_code = 400
    except catalog.TierListCatalogConflictError as exc:
        error = str(exc)
        status_code = 409
    except ValueError as exc:
        error = str(exc)
        status_code = 400
    else:
        return RedirectResponse('/admin/tierlist-catalog', status_code=303)
    return templates.TemplateResponse(
        request=request,
        name='admin/tierlist_catalog_json.html',
        context=_json_context(session, characters_json, version, error),
        status_code=status_code,
    )


@router.get('/new', name='admin_tierlist_catalog_new')
async def tierlist_catalog_new(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request,
        name='admin/tierlist_catalog_editor.html',
        context=_editor_context(
            session, catalog.tierlist_catalog_json(NEW_CHARACTER), is_new=True,
        ),
    )


@router.post('/new', name='admin_tierlist_catalog_create')
async def tierlist_catalog_create(
    request: Request,
    character_json: str = Form(...),
    photo: UploadFile | None = File(None),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    saved_photo = None
    payload = None
    try:
        payload = json.loads(character_json)
        if not isinstance(payload, dict):
            raise ValueError('Персонаж должен быть JSON-объектом')
        saved_photo = await _apply_upload(payload, photo)
        catalog.save_tierlist_character(session['tg_id'], '', payload)
    except json.JSONDecodeError as exc:
        error = f'Ошибка JSON: строка {exc.lineno}, колонка {exc.colno}: {exc.msg}'
    except ValueError as exc:
        error = str(exc)
    else:
        return RedirectResponse('/admin/tierlist-catalog', status_code=303)
    if saved_photo:
        get_media_store().delete_local(saved_photo)
    image = payload.get('image', '') if isinstance(payload, dict) else ''
    return templates.TemplateResponse(
        request=request,
        name='admin/tierlist_catalog_editor.html',
        context=_editor_context(
            session, character_json, error=error, image=image, is_new=True,
        ),
        status_code=400,
    )


@router.get('/{character_id}/edit', name='admin_tierlist_catalog_edit')
async def tierlist_catalog_edit(
    request: Request, character_id: str, session=Depends(require_admin),
):
    record = catalog.get_tierlist_character_record(character_id)
    if not record:
        return templates.TemplateResponse(
            request=request,
            name='admin/tierlist_catalog.html',
            context=_catalog_context(session, error='Персонаж не найден'),
            status_code=404,
        )
    character = record['data']
    return templates.TemplateResponse(
        request=request,
        name='admin/tierlist_catalog_editor.html',
        context=_editor_context(
            session,
            catalog.tierlist_catalog_json(character),
            character_id,
            record['lock_version'],
            image=character['image'],
        ),
    )


@router.post('/{character_id}/edit', name='admin_tierlist_catalog_update')
async def tierlist_catalog_update(
    request: Request,
    character_id: str,
    character_json: str = Form(...),
    version: int = Form(...),
    photo: UploadFile | None = File(None),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    current = catalog.get_tierlist_character_record(character_id)
    if not current:
        return RedirectResponse('/admin/tierlist-catalog', status_code=303)
    saved_photo = None
    payload = None
    try:
        payload = json.loads(character_json)
        if not isinstance(payload, dict):
            raise ValueError('Персонаж должен быть JSON-объектом')
        saved_photo = await _apply_upload(payload, photo)
        catalog.save_tierlist_character(
            session['tg_id'], character_id, payload, version,
        )
    except json.JSONDecodeError as exc:
        error = f'Ошибка JSON: строка {exc.lineno}, колонка {exc.colno}: {exc.msg}'
        status_code = 400
    except catalog.TierListCatalogConflictError as exc:
        error = str(exc)
        status_code = 409
    except ValueError as exc:
        error = str(exc)
        status_code = 400
    else:
        _cleanup_images(
            [current['data']['image']],
            [item['image'] for item in catalog.list_tierlist_characters()],
        )
        return RedirectResponse('/admin/tierlist-catalog', status_code=303)
    if saved_photo:
        get_media_store().delete_local(saved_photo)
    image = payload.get('image', '') if isinstance(payload, dict) else current['data']['image']
    return templates.TemplateResponse(
        request=request,
        name='admin/tierlist_catalog_editor.html',
        context=_editor_context(
            session, character_json, character_id, version, error, image,
        ),
        status_code=status_code,
    )


@router.post('/{character_id}/delete', name='admin_tierlist_catalog_delete')
async def tierlist_catalog_delete(
    character_id: str,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        character = catalog.delete_tierlist_character(session['tg_id'], character_id)
    except ValueError:
        return RedirectResponse('/admin/tierlist-catalog', status_code=303)
    _cleanup_images(
        [character['image']],
        [item['image'] for item in catalog.list_tierlist_characters()],
    )
    return RedirectResponse('/admin/tierlist-catalog', status_code=303)
