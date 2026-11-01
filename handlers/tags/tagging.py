import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from database.queries import (
    get_tag_by_name, get_tag_subscribers, create_tag, touch_tag_last_used,
    find_any_tag_or_alias_owner, log_tag_usage, get_user_language,
)
from services.tag_storage import tag_storage
from services.mentions import mention_users
from services.validation import MAX_NAME_LENGTH, name_is_too_long
from services.video_links import extract_video_tags, extract_video_url
from message.loader import message
from message.keys import tag_suggest, tag_created, tag_no_argument, tag_name_reserved

logger = logging.getLogger(__name__)


def _log_tag_message_usage(update: Update, tag_id: int, user_id: int, media_type: str):
    message_obj = update.effective_message
    metadata = {
        'chat_id': update.effective_chat.id,
        'message_thread_id': message_obj.message_thread_id,
        'caption': message_obj.caption or message_obj.text,
    }
    if media_type == 'photo':
        photo = message_obj.photo[-1]
        metadata['media_file_id'] = photo.file_id
        metadata['media_file_unique_id'] = photo.file_unique_id
    elif media_type == 'video':
        metadata['media_file_id'] = message_obj.video.file_id
        metadata['media_file_unique_id'] = message_obj.video.file_unique_id
    elif media_type == 'video_link':
        metadata['media_url'] = extract_video_url(message_obj.text or '')

    log_tag_usage(
        tag_id, message_obj.message_id, user_id, media_type, **metadata,
    )


def create_subscribe_markup(tag_id: int):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton('Подписаться', callback_data=f'subscribe/{tag_id}')
    ]])


def create_yes_no_markup(matched_tag_id: int, user_id: int):
    buttons = [
        [InlineKeyboardButton('Да', callback_data=f'tag/{matched_tag_id}/{user_id}')],
        [InlineKeyboardButton('Нет', callback_data=f'new/{user_id}')],
    ]
    return InlineKeyboardMarkup(buttons)


async def resolve_tag_subscribers(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tag_name: str,
    *,
    log_usage: bool = False,
    media_type: str | None = None,
) -> list[dict] | None:
    thread_id = update.effective_message.message_thread_id
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    if name_is_too_long(tag_name):
        await update.effective_message.reply_text(
            message(lang, 'common.nameTooLong', 'common', MAX_NAME_LENGTH),
            message_thread_id=thread_id,
        )
        return None

    result = tag_storage.find(tag_name)

    if result['status'] == 'found':
        matched_name = result['tag']
        tag = get_tag_by_name(matched_name)

        if not tag or tag['status'] != 'ACTIVE':
            logger.warning("Тег '%s' из кэша отсутствует в БД или не ACTIVE", matched_name)
            return None

        touch_tag_last_used(tag['id'])
        if log_usage:
            _log_tag_message_usage(update, tag['id'], user_id, media_type)
            logger.info(
                "Зафиксировано использование тега '%s' (сообщение %s, тип %s)",
                matched_name, update.effective_message.message_id, media_type,
            )
        return get_tag_subscribers(tag['id'])

    if result['status'] == 'suggest':
        logger.info(
            "Пользователю %s предложено уточнение: %s -> %s (%.0f%%)",
            user_id, tag_name, result['tag'], result['score'],
        )
        context.user_data['pending_new_tag'] = tag_name
        matched_tag = get_tag_by_name(result['tag'])
        markup = create_yes_no_markup(matched_tag['id'], user_id)
        await update.effective_message.reply_text(
            message(lang, tag_suggest, 'tag', result['tag'], f'{result["score"]:.0f}'),
            reply_markup=markup,
            message_thread_id=thread_id,
        )
        return None

    new_name = result['tag']
    collision = find_any_tag_or_alias_owner(new_name)

    if collision and collision['status'] != 'ACTIVE':
        logger.info("Попытка создать тег '%s' — имя занято скрытым/заблокированным тегом", new_name)
        await update.effective_message.reply_text(
            message(lang, tag_name_reserved, 'tag', new_name),
            message_thread_id=thread_id,
        )
        return None

    if collision and collision['status'] == 'ACTIVE':
        logger.warning("Рассинхрон кэша: '%s' активен в БД, но отсутствовал в tag_storage", collision['name'])
        tag_storage.add_to_cache(collision['name'])
        tag = get_tag_by_name(collision['name'])
        touch_tag_last_used(tag['id'])
        if log_usage:
            _log_tag_message_usage(update, tag['id'], user_id, media_type)
        return get_tag_subscribers(tag['id'])

    new_tag = create_tag(new_name, created_by_tg_id=user_id)
    tag_storage.add_to_cache(new_name)
    logger.info("Пользователь %s создал новый тег: %s", user_id, new_name)

    if log_usage:
        _log_tag_message_usage(update, new_tag['id'], user_id, media_type)

    await update.effective_message.reply_text(
        message(lang, tag_created, 'tag', new_name),
        reply_markup=create_subscribe_markup(new_tag['id']),
        message_thread_id=thread_id,
    )
    return None


async def media_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message:
        return

    message_obj = update.effective_message
    thread_id = message_obj.message_thread_id

    if message_obj.via_bot or message_obj.forward_origin:
        return
    if not message_obj.caption or '#' not in message_obj.caption:
        return

    if message_obj.photo:
        media_type = 'photo'
    elif message_obj.video:
        media_type = 'video'
    else:
        logger.warning("media_tag_handler вызван для сообщения без фото/видео (id=%s)", message_obj.message_id)
        return

    tags = [w[1:] for w in message_obj.caption.split() if w.startswith('#')]
    all_subscribers = []
    for tag_name in tags:
        subs = await resolve_tag_subscribers(
            update, context, tag_name, log_usage=True, media_type=media_type,
        )
        if subs:
            all_subscribers.extend(subs)

    unique_subscribers = list({row['tg_id']: row for row in all_subscribers}.values())
    if unique_subscribers:
        await mention_users(context, update.effective_chat.id, unique_subscribers, thread_id)


async def tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.effective_message.message_thread_id
    lang = get_user_language(update.effective_user.id)

    if not context.args:
        await update.effective_message.reply_text(message(lang, tag_no_argument, 'tag'), message_thread_id=thread_id)
        return

    tags = [w[1:] if w.startswith('#') else w for w in context.args]
    all_subscribers = []
    for tag_name in tags:
        subs = await resolve_tag_subscribers(update, context, tag_name)
        if subs:
            all_subscribers.extend(subs)

    unique_subscribers = list({row['tg_id']: row for row in all_subscribers}.values())
    if unique_subscribers:
        await mention_users(context, update.effective_chat.id, unique_subscribers, thread_id)


async def link_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message:
        return

    message_obj = update.effective_message
    text = message_obj.text or ''
    if message_obj.via_bot or message_obj.forward_origin:
        return

    tags = extract_video_tags(text)
    if not tags:
        return

    all_subscribers = []
    for tag_name in tags:
        subs = await resolve_tag_subscribers(
            update, context, tag_name, log_usage=True, media_type='video_link',
        )
        if subs:
            all_subscribers.extend(subs)

    unique_subscribers = list({row['tg_id']: row for row in all_subscribers}.values())
    if unique_subscribers:
        await mention_users(
            context,
            update.effective_chat.id,
            unique_subscribers,
            message_obj.message_thread_id,
        )
