import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.auth import auth
from services.mentions import mention_users
from services.tag_storage import tag_storage
from database.queries import get_tag_by_name, subscribe_tag, get_tag_subscribers, create_tag, touch_tag_last_used, get_user_language
from handlers.tagging import create_subscribe_markup
from message.loader import message
from message.keys import sub_character_not_found, sub_success, sub_tag_unavailable, tag_created, inline_subscribers_prefix, inline_no_subscribers

logger = logging.getLogger(__name__)


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

    if action == "subscribe":
        tag_name = parts[1]
        tag = get_tag_by_name(tag_name)

        if not tag:
            await context.bot.send_message(
                chat_id, message(lang, sub_character_not_found, 'sub'),
                parse_mode='Markdown', message_thread_id=thread_id,
            )
            return

        # ДОБАВЛЕНО (B2): защита от гонки — кнопка могла быть отрисована
        # до того, как тег заблокировали/удалили, а нажата уже после.
        if tag['status'] != 'ACTIVE':
            logger.info("Кнопка 'Подписаться' нажата на неактивный тег %s (статус %s)", tag_name, tag['status'])
            await context.bot.send_message(
                chat_id, message(lang, sub_tag_unavailable, 'sub'),
                parse_mode='Markdown', message_thread_id=thread_id,
            )
            return

        subscribe_tag(user.id, tag['id'])
        logger.info("Пользователь %s подписался на %s (через кнопку)", user.id, tag_name)

        await context.bot.send_message(
            chat_id, message(lang, sub_success, 'sub', user.username, tag_name),
            parse_mode='Markdown', message_thread_id=thread_id,
        )

        subs = get_tag_subscribers(tag['id'])
        subs_str = ", ".join(s['username'] for s in subs)
        subs_text = (
            message(lang, inline_subscribers_prefix, 'inline', subs_str)
            if subs_str else message(lang, inline_no_subscribers, 'inline')
        )

        await context.bot.edit_message_text(
            f'#{tag_name}\n{subs_text}', chat_id=chat_id, message_id=message_id,
            reply_markup=create_subscribe_markup(tag_name),
        )

    elif action == "tag":
        tag_name, original_user_id = parts[1], parts[2]
        if int(original_user_id) != int(user.id):
            logger.warning("Пользователь %s попытался использовать чужую кнопку tag (%s)", user.id, original_user_id)
            return

        tag = get_tag_by_name(tag_name)
        if tag and tag['status'] == 'ACTIVE':
            touch_tag_last_used(tag['id'])
            subs = get_tag_subscribers(tag['id'])
            subs_usernames = list({s['username'] for s in subs})
            if subs_usernames:
                await mention_users(context, chat_id, subs_usernames, thread_id)
        await context.bot.delete_message(chat_id, message_id)

    elif action == "new":
        tag_name, original_user_id = parts[1], parts[2]
        if int(original_user_id) != int(user.id):
            logger.warning("Пользователь %s попытался использовать чужую кнопку new (%s)", user.id, original_user_id)
            return

        create_tag(tag_name, created_by_tg_id=user.id)
        tag_storage.add_to_cache(tag_name)
        logger.info("Пользователь %s создал тег %s (через кнопку)", user.id, tag_name)

        markup = create_subscribe_markup(tag_name)
        await context.bot.send_message(
            chat_id, message(lang, tag_created, 'tag', tag_name),
            parse_mode='Markdown', reply_markup=markup, message_thread_id=thread_id,
        )
        await context.bot.delete_message(chat_id, message_id)