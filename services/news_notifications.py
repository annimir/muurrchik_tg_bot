import json
import logging
import mimetypes

import httpx
from fastapi import HTTPException

from config.config import config
from database.news import mark_news_telegram_sent
from database.queries import get_active_chats
from services.news_markdown import telegram_news_text
from web.media import get_media_store

logger = logging.getLogger(__name__)


async def send_news_to_telegram(post):
    if not post['is_published'] or post['telegram_message_id']:
        return None
    active_chats = get_active_chats()
    if not active_chats:
        logger.warning('Нет активных чатов для новости %s', post['id'])
        return None
    chat_id = sorted(active_chats, key=lambda chat: chat['chat_id'])[0]['chat_id']
    url = f'{config.web_public_base_url.rstrip("/")}/news/{post["id"]}'
    reply_markup = {'inline_keyboard': [[{'text': 'Читать новость', 'url': url}]]}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            if post.get('cover_image'):
                filename = post['cover_image'].removeprefix('/media/news/')
                path = get_media_store().get_local_path(f'local:{filename}')
                response = await client.post(
                    f'https://api.telegram.org/bot{config.bot_token}/sendPhoto',
                    data={
                        'chat_id': chat_id,
                        'caption': telegram_news_text(post, max_source_length=800),
                        'parse_mode': 'HTML',
                        'reply_markup': json.dumps(reply_markup),
                    },
                    files={
                        'photo': (
                            path.name, path.read_bytes(),
                            mimetypes.guess_type(path.name)[0] or 'image/webp',
                        ),
                    },
                )
            else:
                response = await client.post(
                    f'https://api.telegram.org/bot{config.bot_token}/sendMessage',
                    json={
                        'chat_id': chat_id,
                        'text': telegram_news_text(post),
                        'parse_mode': 'HTML',
                        'reply_markup': reply_markup,
                    },
                )
            response.raise_for_status()
            payload = response.json()
        if not payload.get('ok'):
            logger.warning('Telegram отклонил новость %s', post['id'])
            return None
    except (httpx.HTTPError, ValueError, OSError, HTTPException) as exc:
        logger.warning('Не удалось отправить новость %s: %s', post['id'], type(exc).__name__)
        return None
    return mark_news_telegram_sent(post['id'], payload['result']['message_id'])
