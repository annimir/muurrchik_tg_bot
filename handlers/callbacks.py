import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.auth import auth
from services.mentions import mention_users
from services.tag_storage import tag_storage
from database.queries import (
    subscribe_character, get_character_by_name, get_character_subscribers,
    create_character, delete_character, get_user_language,
)
from handlers.tagging import create_subscribe_markup
from message.loader import message
from message.keys import (
    sub_character_not_found, sub_success, tag_created, char_deleted,
    inline_subscribers_prefix, inline_no_subscribers,
)

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
        character_name = parts[1]
        character = get_character_by_name(character_name)

        if character:
            subscribe_character(character_name, user.id)
            logger.info("Пользователь %s подписался на %s (через кнопку)", user.id, character_name)

            await context.bot.send_message(
                chat_id, message(lang, sub_success, 'sub', user.username, character_name),
                parse_mode='Markdown', message_thread_id=thread_id,
            )

            subs = get_character_subscribers(character_name)
            subs_str = ", ".join(s['tag'] for s in subs)
            subs_text = (
                message(lang, inline_subscribers_prefix, 'inline', subs_str)
                if subs_str else message(lang, inline_no_subscribers, 'inline')
            )

            await context.bot.edit_message_text(
                f'#{character_name}\n{subs_text}',
                chat_id=chat_id, message_id=message_id,
                reply_markup=create_subscribe_markup(character_name),
            )
        else:
            await context.bot.send_message(
                chat_id, message(lang, sub_character_not_found, 'sub'),
                parse_mode='Markdown', message_thread_id=thread_id,
            )

    elif action == "tag":
        character_name, original_user_id = parts[1], parts[2]
        if int(original_user_id) != int(user.id):
            logger.warning("Пользователь %s попытался использовать чужую кнопку tag (%s)", user.id, original_user_id)
            return

        subs = get_character_subscribers(character_name)
        subs = list({s['tag'] for s in subs})
        if subs:
            await mention_users(context, chat_id, subs, thread_id)
        await context.bot.delete_message(chat_id, message_id)

    elif action == "new":
        character_name, original_user_id = parts[1], parts[2]
        if int(original_user_id) != int(user.id):
            logger.warning("Пользователь %s попытался использовать чужую кнопку new (%s)", user.id, original_user_id)
            return

        create_character(character_name)
        tag_storage.add_to_cache(character_name)
        logger.info("Пользователь %s создал персонажа %s (через кнопку)", user.id, character_name)

        markup = create_subscribe_markup(character_name, user.id)
        await context.bot.send_message(
            chat_id, message(lang, tag_created, 'tag', character_name),
            parse_mode='Markdown', reply_markup=markup, message_thread_id=thread_id,
        )
        await context.bot.delete_message(chat_id, message_id)

    elif action == "del":
        character_name, original_user_id = parts[1], parts[2]
        if int(original_user_id) != int(user.id):
            logger.warning("Пользователь %s попытался использовать чужую кнопку del (%s)", user.id, original_user_id)
            return

        delete_character(character_name)
        tag_storage.tags.pop(tag_storage.normalize(character_name), None)
        logger.info("Пользователь %s удалил персонажа %s (через кнопку)", user.id, character_name)

        await context.bot.send_message(
            chat_id, message(lang, char_deleted, 'char', character_name),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        await context.bot.delete_message(chat_id, message_id)