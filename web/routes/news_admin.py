from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from database.news import (
    create_news, delete_news, get_admin_news, list_admin_news, update_news,
)
from services.news_notifications import send_news_to_telegram
from web.auth import csrf_protect, require_admin
from web.rendering import templates

router = APIRouter(prefix='/admin/news')
ERRORS = {
    'telegram': 'Новость сохранена на сайте, но отправить её в Telegram не удалось. Попробуйте ещё раз позже.',
    'not_found': 'Новость не найдена',
}


def _list_context(session, error=None):
    return {
        'posts': list_admin_news(),
        'csrf_token': session['csrf'],
        'active_page': 'admin_news',
        'error': error,
    }


def _form_context(session, post=None, error=None, send_telegram=False):
    post = post or {
        'title': '', 'summary': '', 'content': '', 'is_published': False,
        'telegram_message_id': None,
    }
    return {
        'post': post,
        'send_telegram': send_telegram,
        'csrf_token': session['csrf'],
        'active_page': 'admin_news',
        'error': error,
    }


async def _send_if_requested(post, send_telegram):
    if send_telegram and post['is_published'] and not post['telegram_message_id']:
        sent = await send_news_to_telegram(post)
        return sent is not None
    return True


@router.get('', name='admin_news')
async def news_list(request: Request, error: str = '', session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request,
        name='admin/news.html',
        context=_list_context(session, ERRORS.get(error)),
    )


@router.get('/new', name='admin_news_new')
async def news_new(request: Request, session=Depends(require_admin)):
    return templates.TemplateResponse(
        request=request, name='admin/news_edit.html', context=_form_context(session),
    )


@router.post('/new', name='admin_news_create')
async def news_create(
    request: Request,
    title: str = Form(...),
    summary: str = Form(...),
    content: str = Form(...),
    is_published: bool = Form(False),
    send_telegram: bool = Form(False),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    post = {
        'title': title, 'summary': summary, 'content': content,
        'is_published': is_published, 'telegram_message_id': None,
    }
    try:
        saved = create_news(session['tg_id'], title, summary, content, is_published)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name='admin/news_edit.html',
            context=_form_context(session, post, str(exc), send_telegram),
            status_code=400,
        )
    sent = await _send_if_requested(saved, send_telegram)
    return RedirectResponse(
        '/admin/news' if sent else '/admin/news?error=telegram', status_code=303,
    )


@router.get('/{news_id}/edit', name='admin_news_edit')
async def news_edit(request: Request, news_id: int, session=Depends(require_admin)):
    post = get_admin_news(news_id)
    if not post:
        raise HTTPException(status_code=404, detail='Новость не найдена')
    return templates.TemplateResponse(
        request=request, name='admin/news_edit.html', context=_form_context(session, post),
    )


@router.post('/{news_id}/edit', name='admin_news_update')
async def news_update(
    request: Request,
    news_id: int,
    title: str = Form(...),
    summary: str = Form(...),
    content: str = Form(...),
    is_published: bool = Form(False),
    send_telegram: bool = Form(False),
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    post = {
        'title': title, 'summary': summary, 'content': content,
        'is_published': is_published, 'telegram_message_id': None,
    }
    try:
        saved = update_news(session['tg_id'], news_id, title, summary, content, is_published)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name='admin/news_edit.html',
            context=_form_context(session, post, str(exc), send_telegram),
            status_code=400,
        )
    sent = await _send_if_requested(saved, send_telegram)
    return RedirectResponse(
        '/admin/news' if sent else '/admin/news?error=telegram', status_code=303,
    )


@router.post('/{news_id}/delete', name='admin_news_delete')
async def news_delete(
    news_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    try:
        delete_news(session['tg_id'], news_id)
    except ValueError:
        pass
    return RedirectResponse('/admin/news', status_code=303)


@router.post('/{news_id}/telegram', name='admin_news_telegram')
async def news_telegram(
    news_id: int,
    session=Depends(require_admin),
    _=Depends(csrf_protect),
):
    post = get_admin_news(news_id)
    if not post:
        raise HTTPException(status_code=404, detail='Новость не найдена')
    sent = await _send_if_requested(post, True)
    return RedirectResponse(
        '/admin/news' if sent else '/admin/news?error=telegram', status_code=303,
    )
