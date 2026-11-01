import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.auth import auth
from services.mentions import mention_users
from services.tag_storage import tag_storage
from database.queries import (
    get_tag_by_id, get_tag_by_name, subscribe_tag, get_tag_subscribers,
    create_tag, touch_tag_last_used, get_user_language, find_any_tag_or_alias_owner,
)
from handlers.tags.tagging import create_subscribe_markup
from message.loader import message
from message.keys import (
    sub_character_not_found, sub_success, sub_tag_unavailable,
    tag_created, tag_name_reserved, inline_subscribers_prefix, inline_no_subscribers,
)

logger = logging.getLogger(__name__)


def _get_tag(identifier: str):
    if identifier.isdigit():
        return get_tag_by_id(int(identifier))
    return get_tag_by_name(identifier)


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    call = update.callback_query
    await call.answer()

    user = call.from_user
    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    chat_id = call.message.chat.id if call.message else None
    thread_id = call.message.message_thread_id if call.message else None
    message_id = call.message.message_id if call.message else None

    parts = call.data.split('/')
    action = parts[0]

    if action == 'subscribe':
        tag = _get_tag(parts[1])
        if not tag:
            await context.bot.send_message(
                chat_id,
                message(lang, sub_character_not_found, 'sub'),
                message_thread_id=thread_id,
            )
            return

        if tag['status'] != 'ACTIVE':
            logger.info("Кнопка 'Подписаться' нажата на неактивный тег %s", tag['name'])
            await context.bot.send_message(
                chat_id,
                message(lang, sub_tag_unavailable, 'sub'),
                message_thread_id=thread_id,
            )
            return

        subscribe_tag(user.id, tag['id'])
        logger.info("Пользователь %s подписался на %s (через кнопку)", user.id, tag['name'])
        await context.bot.send_message(
            chat_id,
            message(lang, sub_success, 'sub', user.username, tag['name']),
            message_thread_id=thread_id,
        )

        subs = get_tag_subscribers(tag['id'])
        subs_str = ', '.join(s['username'] for s in subs if s['username'])
        subs_text = (
            message(lang, inline_subscribers_prefix, 'inline', subs_str)
            if subs_str else message(lang, inline_no_subscribers, 'inline')
        )
        new_text = f'#{tag["name"]}\n{subs_text}'
        if call.message.text != new_text:
            await context.bot.edit_message_text(
                new_text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=create_subscribe_markup(tag['id']),
            )

    elif action == 'tag':
        original_user_id = parts[2]
        if int(original_user_id) != user.id:
            logger.warning("Пользователь %s попытался использовать чужую кнопку tag", user.id)
            return

        tag = _get_tag(parts[1])
        if tag and tag['status'] == 'ACTIVE':
            touch_tag_last_used(tag['id'])
            subscribers = get_tag_subscribers(tag['id'])
            if subscribers:
                await mention_users(context, chat_id, subscribers, thread_id)
        await context.bot.delete_message(chat_id, message_id)

    elif action == 'new':
        original_user_id = parts[1] if len(parts) == 2 else parts[2]
        if int(original_user_id) != user.id:
            logger.warning("Пользователь %s попытался использовать чужую кнопку new", user.id)
            return

        tag_name = context.user_data.pop('pending_new_tag', None)
        if not tag_name and len(parts) > 2:
            tag_name = parts[1]
        if not tag_name:
            await context.bot.delete_message(chat_id, message_id)
            return

        collision = find_any_tag_or_alias_owner(tag_name)
        if collision:
            await context.bot.send_message(
                chat_id,
                message(lang, tag_name_reserved, 'tag', tag_name),
                message_thread_id=thread_id,
            )
            await context.bot.delete_message(chat_id, message_id)
            return

        tag = create_tag(tag_name, created_by_tg_id=user.id)
        tag_storage.add_to_cache(tag_name)
        logger.info("Пользователь %s создал тег %s (через кнопку)", user.id, tag_name)
        await context.bot.send_message(
            chat_id,
            message(lang, tag_created, 'tag', tag_name),
            reply_markup=create_subscribe_markup(tag['id']),
            message_thread_id=thread_id,
        )
        await context.bot.delete_message(chat_id, message_id)
