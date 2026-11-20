from fastapi import APIRouter, HTTPException, Request

from database.news import get_public_news, list_news_tags, list_public_news
from services.news_markdown import render_news_markdown
from web.media import get_media_store
from web.rendering import templates

router = APIRouter()


@router.get('/news', name='news_page')
async def news_page(request: Request, tag: str = ''):
    return templates.TemplateResponse(
        request=request,
        name='news.html',
        context={
            'posts': list_public_news(tag=tag.strip()),
            'tags': list_news_tags(),
            'selected_tag': tag.strip(),
            'active_page': 'news',
        },
    )


@router.get('/news/{news_id}', name='news_detail')
async def news_detail(request: Request, news_id: int):
    post = get_public_news(news_id)
    if not post:
        raise HTTPException(status_code=404, detail='Новость не найдена')
    return templates.TemplateResponse(
        request=request,
        name='news_detail.html',
        context={
            'post': post,
            'content_html': render_news_markdown(post['content']),
            'active_page': 'news',
        },
    )


@router.get('/media/news/{filename}', name='news_cover_image')
async def news_cover_image(filename: str):
    return get_media_store().get_local_response(f'local:{filename}')
