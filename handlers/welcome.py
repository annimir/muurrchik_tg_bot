import logging

from telegram import Update
from telegram.ext import ContextTypes

from message.loader import message
from message.keys import welcome_message

logger = logging.getLogger(__name__)


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    for member in update.message.new_chat_members:
        if member.is_bot:
            continue

        lang = 'RU' if member.language_code == 'ru' else 'EN'
        mention = f'<a href="tg://user?id={member.id}">{member.full_name}</a>'
        text = message(lang, welcome_message, 'welcome')

        await update.message.reply_text(f'{mention}\n\n{text}', parse_mode='HTML')
        logger.info("Приветствие отправлено новому участнику %s в чате %s", member.id, chat_id)