import logging

from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import ContextTypes

from database.queries import upsert_chat, deactivate_chat

logger = logging.getLogger(__name__)


async def track_bot_membership(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.my_chat_member
    chat = result.chat
    new_status = result.new_chat_member.status

    if new_status in (ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR):
        upsert_chat(chat.id, chat.title or str(chat.id))
        logger.info("Бот добавлен/активен в чате %s (%s)", chat.id, chat.title)
    elif new_status in (ChatMemberStatus.LEFT, ChatMemberStatus.KICKED):
        deactivate_chat(chat.id)
        logger.info("Бот удалён из чата %s (%s)", chat.id, chat.title)