import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import get_user_by_tg_id, create_user, upsert_membership, mark_user_returned
from message.loader import message
from message.keys import welcome_message

logger = logging.getLogger(__name__)


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    for member in update.effective_message.new_chat_members:
        if member.is_bot:
            continue

        db_user = get_user_by_tg_id(member.id)
        if not db_user:
            create_user(member.id, member.username or member.full_name)
            db_user = get_user_by_tg_id(member.id)

        upsert_membership(db_user['id'], chat_id, is_member=True)
        mark_user_returned(db_user['id'])

        lang = 'RU' if member.language_code == 'ru' else 'EN'
        display_name = html.escape(member.full_name, quote=False)
        mention = f'<a href="tg://user?id={member.id}">{display_name}</a>'
        text = message(lang, welcome_message, 'welcome')

        await update.effective_message.reply_text(f'{mention}\n\n{text}', parse_mode='HTML')
        logger.info("Приветствие отправлено новому участнику %s в чате %s", member.id, chat_id)