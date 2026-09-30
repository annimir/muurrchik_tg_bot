import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.auth import auth
from database.queries import get_user_subscriptions, get_tag_by_name, subscribe_tag, unsubscribe_tag, get_user_language
from message.loader import message
from message.keys import (
    sub_no_argument, sub_character_not_found, sub_success, sub_tag_unavailable,
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
            update.effective_chat.id, message(lang, mysub_empty, 'mysub', user.username),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    for i in range(0, len(all_subs), PAGE_SIZE):
        page = all_subs[i:i + PAGE_SIZE]
        names = ", ".join(s['name'] for s in page)
        text = message(lang, mysub_list, 'mysub', user.username, names) if i == 0 else names
        await context.bot.send_message(
            update.effective_chat.id, text, parse_mode='Markdown', message_thread_id=thread_id,
        )


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.message.message_thread_id

    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    if not context.args:
        await update.message.reply_text(message(lang, sub_no_argument, 'sub'), message_thread_id=thread_id)
        return

    tag_name = context.args[0].lower()
    tag = get_tag_by_name(tag_name)

    if not tag:
        logger.warning("Пользователь %s пытался подписаться на несуществующий тег %s", user.id, tag_name)
        await context.bot.send_message(
            update.effective_chat.id, message(lang, sub_character_not_found, 'sub'),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    # подписаться на DELETED/BLOCKED тег в обход тегирования по фото.
    if tag['status'] != 'ACTIVE':
        logger.info("Пользователь %s пытался подписаться на тег %s в статусе %s", user.id, tag_name, tag['status'])
        await context.bot.send_message(
            update.effective_chat.id, message(lang, sub_tag_unavailable, 'sub'),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    subscribe_tag(user.id, tag['id'])
    logger.info("Пользователь %s подписался на тег %s", user.id, tag_name)
    await context.bot.send_message(
        update.effective_chat.id, message(lang, sub_success, 'sub', user.username, tag_name),
        parse_mode='Markdown', message_thread_id=thread_id,
    )


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.message.message_thread_id

    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    if not context.args:
        await update.message.reply_text(message(lang, sub_no_argument, 'sub'), message_thread_id=thread_id)
        return

    tag_name = context.args[0].lower()
    tag = get_tag_by_name(tag_name)

    if not tag:
        await context.bot.send_message(
            update.effective_chat.id, message(lang, sub_character_not_found, 'sub'),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    # Отписка НЕ проверяет статус тега намеренно — пользователь должен
    # иметь возможность выйти из подписки на DELETED/BLOCKED тег в любой момент,
    # даже если новые подписки на него запрещены.
    unsubscribe_tag(user.id, tag['id'])
    logger.info("Пользователь %s отписался от тега %s", user.id, tag_name)
    await context.bot.send_message(
        update.effective_chat.id, message(lang, unsub_success, 'unsub', user.username, tag_name),
        parse_mode='Markdown', message_thread_id=thread_id,
    )