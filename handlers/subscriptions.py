import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.auth import auth
from database.queries import (
    get_user_subscriptions, get_character_by_name,
    subscribe_character, unsubscribe_character, get_user_language,
)
from message.loader import message
from message.keys import (
    sub_no_argument, sub_character_not_found, sub_success,
    unsub_success, mysub_empty, mysub_list,
)

logger = logging.getLogger(__name__)

PAGE_SIZE = 40


async def my_subscriptions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.message.message_thread_id

    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    all_subs = get_user_subscriptions(user.id)

    if not all_subs:
        await context.bot.send_message(
            update.effective_chat.id,
            message(lang, mysub_empty, 'mysub', user.username),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    for i in range(0, len(all_subs), PAGE_SIZE):
        page = all_subs[i:i + PAGE_SIZE]
        names = ", ".join(s['name'] for s in page)

        text = message(lang, mysub_list, 'mysub', user.username, names) if i == 0 else names
        await context.bot.send_message(
            update.effective_chat.id, text,
            parse_mode='Markdown', message_thread_id=thread_id,
        )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.message.message_thread_id

    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    if not context.args:
        await update.message.reply_text(
            message(lang, sub_no_argument, 'sub'), message_thread_id=thread_id,
        )
        return

    character_name = context.args[0].lower()
    character = get_character_by_name(character_name)

    if not character:
        logger.warning("Пользователь %s пытался подписаться на несуществующего персонажа %s", user.id, character_name)
        await context.bot.send_message(
            update.effective_chat.id, message(lang, sub_character_not_found, 'sub'),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    subscribe_character(character_name, user.id)
    logger.info("Пользователь %s подписался на %s", user.id, character_name)
    await context.bot.send_message(
        update.effective_chat.id,
        message(lang, sub_success, 'sub', user.username, character_name),
        parse_mode='Markdown', message_thread_id=thread_id,
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.message.message_thread_id

    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    if not context.args:
        await update.message.reply_text(
            message(lang, sub_no_argument, 'sub'), message_thread_id=thread_id,
        )
        return

    character_name = context.args[0].lower()
    character = get_character_by_name(character_name)

    if not character:
        await context.bot.send_message(
            update.effective_chat.id, message(lang, sub_character_not_found, 'sub'),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    unsubscribe_character(character_name, user.id)
    logger.info("Пользователь %s отписался от %s", user.id, character_name)
    await context.bot.send_message(
        update.effective_chat.id,
        message(lang, unsub_success, 'unsub', user.username, character_name),
        parse_mode='Markdown', message_thread_id=thread_id,
    )