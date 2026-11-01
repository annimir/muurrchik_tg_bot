import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.auth import auth
from database.queries import get_user_language
from message.loader import message
from message.keys import profile_updated

logger = logging.getLogger(__name__)


async def update_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.effective_message.message_thread_id

    await auth(user.id, user.username)
    lang = get_user_language(user.id)
    logger.info("Пользователь %s обновил свой профиль (tag=%s)", user.id, user.username)

    await context.bot.send_message(
        update.effective_chat.id, message(lang, profile_updated, 'profile', user.username),
        parse_mode=None, message_thread_id=thread_id,
    )