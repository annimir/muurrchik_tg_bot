import logging

import httpx

from config.config import config
from database.queries import get_active_chats
from database.tierlists import mark_tier_list_announcement_sent

logger = logging.getLogger(__name__)


async def announce_tier_list(tier_list):
    active_chats = get_active_chats()
    if not active_chats:
        logger.warning('Нет активных чатов для объявления тирлиста %s', tier_list['id'])
        return False

    chat_id = sorted(active_chats, key=lambda chat: chat['chat_id'])[0]['chat_id']
    owner = tier_list['owner_tag'] or 'Игрок'
    url = f'{config.web_public_base_url.rstrip("/")}/tierlists/{tier_list["id"]}'
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f'https://api.telegram.org/bot{config.bot_token}/sendMessage',
                json={
                    'chat_id': chat_id,
                    'text': f'{owner} создал тирлист «{tier_list["title"]}»',
                    'reply_markup': {
                        'inline_keyboard': [[{'text': 'Открыть тирлист', 'url': url}]],
                    },
                },
            )
            response.raise_for_status()
            payload = response.json()
        if not payload.get('ok'):
            logger.warning('Telegram отклонил объявление тирлиста %s', tier_list['id'])
            return False
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning(
            'Не удалось объявить тирлист %s: %s', tier_list['id'], type(exc).__name__,
        )
        return False

    mark_tier_list_announcement_sent(tier_list['id'])
    return True
