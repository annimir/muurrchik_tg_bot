from fastapi import APIRouter, HTTPException, Request

from database.news import get_public_news, list_public_news
from web.rendering import templates

router = APIRouter()


@router.get('/news', name='news_page')
async def news_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name='news.html',
        context={'posts': list_public_news(), 'active_page': 'news'},
    )


@router.get('/news/{news_id}', name='news_detail')
async def news_detail(request: Request, news_id: int):
    post = get_public_news(news_id)
    if not post:
        raise HTTPException(status_code=404, detail='Новость не найдена')
    return templates.TemplateResponse(
        request=request,
        name='news_detail.html',
        context={'post': post, 'active_page': 'news'},
    )
