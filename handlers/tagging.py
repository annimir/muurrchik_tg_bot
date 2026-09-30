import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from database.queries import (
    get_tag_by_name, get_tag_subscribers, create_tag, touch_tag_last_used,
    find_any_tag_or_alias_owner, log_tag_usage, get_user_language,
)
from services.tag_storage import tag_storage
from services.mentions import mention_users
from message.loader import message
from message.keys import tag_suggest, tag_created, tag_no_argument, tag_name_reserved

logger = logging.getLogger(__name__)


def create_subscribe_markup(tag_name: str):
    return InlineKeyboardMarkup([[InlineKeyboardButton('Подписаться', callback_data=f'subscribe/{tag_name}')]])


def create_yes_no_markup(matched_name: str, typed_name: str, user_id: int):
    buttons = [
        [InlineKeyboardButton('Да', callback_data=f'tag/{matched_name}/{user_id}')],
        [InlineKeyboardButton('Нет', callback_data=f'new/{typed_name}/{user_id}')],
    ]
    return InlineKeyboardMarkup(buttons)


async def resolve_tag_subscribers(
    update: Update,
    tag_name: str,
    *,
    log_usage: bool = False,
    media_type: str | None = None,
) -> list[str] | None:
    thread_id = update.message.message_thread_id
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    result = tag_storage.find(tag_name)

    if result["status"] == "found":
        matched_name = result["tag"]
        tag = get_tag_by_name(matched_name)

        if not tag or tag['status'] != 'ACTIVE':
            logger.warning("Рассинхрон кэша: '%s' в tag_storage, но в БД статус не ACTIVE", matched_name)
            tag_storage.tags.pop(tag_storage.normalize(matched_name), None)
            return None

        touch_tag_last_used(tag['id'])

        if log_usage:
            log_tag_usage(tag['id'], update.message.message_id, user_id, media_type)
            logger.info("Зафиксировано использование тега '%s' (сообщение %s, тип %s)", matched_name, update.message.message_id, media_type)

        subs = get_tag_subscribers(tag['id'])
        return [s['username'] for s in subs]

    if result["status"] == "suggest":
        logger.info("Пользователю %s предложено уточнение: %s -> %s (%.0f%%)", user_id, tag_name, result["tag"], result["score"])
        markup = create_yes_no_markup(result["tag"], tag_name, user_id)
        await update.message.reply_text(
            message(lang, tag_suggest, 'tag', result["tag"], f'{result["score"]:.0f}'),
            parse_mode='Markdown', reply_markup=markup, message_thread_id=thread_id,
        )
        return None

    new_name = result["tag"]
    collision = find_any_tag_or_alias_owner(new_name)

    if collision and collision['status'] != 'ACTIVE':
        logger.info("Попытка создать тег '%s' — имя занято скрытым/заблокированным тегом", new_name)
        await update.message.reply_text(
            message(lang, tag_name_reserved, 'tag', new_name), message_thread_id=thread_id,
        )
        return None

    if collision and collision['status'] == 'ACTIVE':
        logger.warning("Рассинхрон кэша: '%s' активен в БД, но отсутствовал в tag_storage", collision['name'])
        tag_storage.add_to_cache(collision['name'])
        tag = get_tag_by_name(collision['name'])
        touch_tag_last_used(tag['id'])
        if log_usage:
            log_tag_usage(tag['id'], update.message.message_id, user_id, media_type)
        subs = get_tag_subscribers(tag['id'])
        return [s['username'] for s in subs]

    new_tag = create_tag(new_name, created_by_tg_id=user_id)
    tag_storage.add_to_cache(new_name)
    logger.info("Пользователь %s создал новый тег: %s", user_id, new_name)

    if log_usage:
        log_tag_usage(new_tag['id'], update.message.message_id, user_id, media_type)

    markup = create_subscribe_markup(new_name)
    await update.message.reply_text(
        message(lang, tag_created, 'tag', new_name),
        parse_mode='Markdown', reply_markup=markup, message_thread_id=thread_id,
    )
    return None


async def media_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ПЕРЕИМЕНОВАНО (было photo_tag_handler): теперь обрабатывает и фото, и
    видео с тегом в подписи.
    Тип медиа определяется динамически, а не жёстко зашит как 'photo'.
    """
    message_obj = update.message
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
        # теоретически недостижимо при текущем фильтре регистрации,
        # но не полагаемся молча на то, что фильтр никогда не изменится
        logger.warning("media_tag_handler вызван для сообщения без фото/видео (id=%s)", message_obj.message_id)
        return

    tags = [w[1:] for w in message_obj.caption.split() if w.startswith('#')]

    all_subscribers = []
    for tag_name in tags:
        subs = await resolve_tag_subscribers(update, tag_name, log_usage=True, media_type=media_type)
        if subs:
            all_subscribers.extend(subs)

    all_subscribers = list(set(all_subscribers))
    if all_subscribers:
        await mention_users(context, update.effective_chat.id, all_subscribers, thread_id)


async def tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id
    lang = get_user_language(update.effective_user.id)

    if not context.args:
        await update.message.reply_text(message(lang, tag_no_argument, 'tag'), message_thread_id=thread_id)
        return

    tags = [w[1:] if w.startswith('#') else w for w in context.args]

    all_subscribers = []
    for tag_name in tags:
        subs = await resolve_tag_subscribers(update, tag_name)
        if subs:
            all_subscribers.extend(subs)

    all_subscribers = list(set(all_subscribers))
    if all_subscribers:
        await mention_users(context, update.effective_chat.id, all_subscribers, thread_id)