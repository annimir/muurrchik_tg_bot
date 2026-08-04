import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import get_user_language, set_user_language
from message.loader import message
from message.keys import (
    language_no_argument_exception, language_no_correct_exception,
    language_warning, language_set,
)

logger = logging.getLogger(__name__)

SUPPORTED = ('RU', 'EN')

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    thread_id = update.message.message_thread_id
    current_lang = get_user_language(user_id)

    if not context.args:
        await update.message.reply_text(
            message(current_lang, language_no_argument_exception, 'language'),
            message_thread_id=thread_id,
        )
        return

    new_lang = context.args[0].upper()

    if new_lang not in SUPPORTED:
        logger.warning("Пользователь %s указал неверный код языка: %s", user_id, new_lang)
        await update.message.reply_text(
            message(current_lang, language_no_correct_exception, 'language'),
            message_thread_id=thread_id,
        )
        return

    if new_lang == current_lang:
        await update.message.reply_text(
            message(current_lang, language_warning, 'language', new_lang),
            message_thread_id=thread_id,
        )
        return

    set_user_language(user_id, new_lang)
    logger.info("Пользователь %s сменил язык на %s", user_id, new_lang)
    await update.message.reply_text(
        message(new_lang, language_set, 'language', new_lang),
        message_thread_id=thread_id,
    )