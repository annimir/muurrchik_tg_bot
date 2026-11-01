import logging

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from config.config import config
from database.queries import (
    create_tag, get_existing_youtube_video_ids, get_tag_by_name,
    get_tag_subscribers, record_youtube_publication,
)
from services.mentions import mention_users
from services.tag_storage import tag_storage
from services.youtube import YouTubeClient, classify_video_ids, select_latest_by_kind

logger = logging.getLogger(__name__)

youtube_client = (
    YouTubeClient(config.youtube_api_key, config.youtube_channel_handle)
    if config.youtube_enabled and config.youtube_api_key else None
)


async def notify_youtube_subscribers(context, kind):
    subscribers = []
    for tag_name in ('muuurrchik', kind):
        tag = get_tag_by_name(tag_name)
        if not tag:
            tag = create_tag(tag_name)
            tag_storage.add_to_cache(tag_name)
        if tag['status'] != 'ACTIVE':
            logger.warning("Уведомления для тега '%s' пропущены: статус %s", tag_name, tag['status'])
            continue
        subscribers.extend(get_tag_subscribers(tag['id']))

    unique_subscribers = list({row['tg_id']: row for row in subscribers}.values())
    if unique_subscribers:
        await mention_users(
            context,
            config.youtube_target_chat_id,
            unique_subscribers,
        )


async def publish_youtube_upload(context, upload, kind):
    video_id = upload['video_id']
    if kind == 'shorts':
        url = f'https://www.youtube.com/shorts/{video_id}'
    else:
        url = f'https://www.youtube.com/watch?v={video_id}'

    sent = await context.bot.send_message(
        chat_id=config.youtube_target_chat_id,
        text=f'{url}\n#muuurrchik #{kind}',
    )
    recorded = record_youtube_publication(
        video_id=video_id,
        kind=kind,
        title=upload['title'],
        url=url,
        published_at=upload['published_at'],
        chat_id=config.youtube_target_chat_id,
        message_id=sent.message_id,
    )
    if not recorded:
        return

    logger.info("Опубликовано YouTube %s: %s", kind, video_id)
    try:
        await notify_youtube_subscribers(context, kind)
    except TelegramError as exc:
        logger.warning('Не удалось уведомить подписчиков YouTube %s: %s', video_id, exc)


async def check_youtube_channel(context: ContextTypes.DEFAULT_TYPE):
    if not config.youtube_enabled:
        return
    if not youtube_client or not config.youtube_target_chat_id:
        logger.error('YouTube-интеграция включена, но API key или target_chat_id не настроены')
        return

    try:
        uploads = await youtube_client.fetch_latest_uploads()
        existing = get_existing_youtube_video_ids([item['video_id'] for item in uploads])
        classifications = await classify_video_ids(
            config.youtube_channel_handle,
            [item['video_id'] for item in uploads],
        )
        latest = select_latest_by_kind(uploads, classifications)
        for kind, upload in latest.items():
            if upload['video_id'] not in existing:
                await publish_youtube_upload(context, upload, kind)
    except Exception:
        logger.exception('Не удалось проверить YouTube-канал')
