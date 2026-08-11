import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.queries import unsubscribe_all_tags, count_active_subscriptions, get_user_language
from message.loader import message
from message.keys import (
    unsuball_empty, unsuball_confirm, unsuball_confirm_yes, unsuball_confirm_no,
    unsuball_cancelled, unsuball_done, unsuball_no_pending,
)

logger = logging.getLogger(__name__)


async def unsuball_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)
    thread_id = update.message.message_thread_id

    count = count_active_subscriptions(user.id)

    if count == 0:
        await update.message.reply_text(message(lang, unsuball_empty, 'unsuball'), message_thread_id=thread_id)
        return

    keyboard = [[
        InlineKeyboardButton(message(lang, unsuball_confirm_yes, 'unsuball'), callback_data='unsuballconfirm:yes'),
        InlineKeyboardButton(message(lang, unsuball_confirm_no, 'unsuball'), callback_data='unsuballconfirm:no'),
    ]]
    await update.message.reply_text(
        message(lang, unsuball_confirm, 'unsuball', count),
        reply_markup=InlineKeyboardMarkup(keyboard), message_thread_id=thread_id,
    )


async def unsuball_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = get_user_language(user.id)
    choice = query.data.split(':')[1]

    if choice == 'no':
        await query.edit_message_text(message(lang, unsuball_cancelled, 'unsuball'))
        return

    # повторно проверяем количество на случай гонки (подписки могли измениться между показом кнопок и нажатием)
    count = count_active_subscriptions(user.id)
    if count == 0:
        await query.edit_message_text(message(lang, unsuball_empty, 'unsuball'))
        return

    unsubscribe_all_tags(user.id)
    logger.info("Пользователь %s массово отписался от %d тегов", user.id, count)

    await query.edit_message_text(message(lang, unsuball_done, 'unsuball', count))