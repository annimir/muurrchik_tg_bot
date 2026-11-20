import logging

import httpx

from config.config import config
from database.news import mark_news_telegram_sent
from database.queries import get_active_chats

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
    text = f'{post["title"]}\n\n{post["summary"]}'
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f'https://api.telegram.org/bot{config.bot_token}/sendMessage',
                json={
                    'chat_id': chat_id,
                    'text': text,
                    'reply_markup': {
                        'inline_keyboard': [[{'text': 'Читать новость', 'url': url}]],
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
        if not payload.get('ok'):
            logger.warning('Telegram отклонил новость %s', post['id'])
            return None
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning('Не удалось отправить новость %s: %s', post['id'], type(exc).__name__)
        return None
    return mark_news_telegram_sent(post['id'], payload['result']['message_id'])
