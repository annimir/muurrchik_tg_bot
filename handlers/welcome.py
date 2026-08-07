import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import get_user_by_tg_id, create_user, upsert_membership, mark_user_returned, get_user_flavor_role
from services.flavor_roles import assign_random_role
from message.loader import message
from message.keys import welcome_message, welcome_role_assigned

logger = logging.getLogger(__name__)


async def welcome_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    for member in update.message.new_chat_members:
        if member.is_bot:
            continue

        db_user = get_user_by_tg_id(member.id)
        if not db_user:
            create_user(member.id, member.username or member.full_name)
            db_user = get_user_by_tg_id(member.id)

        upsert_membership(db_user['id'], chat_id, is_member=True)
        mark_user_returned(db_user['id'])

        existing_role = get_user_flavor_role(db_user['id'])
        if existing_role:
            role_name = existing_role['name']  # роль фиксируется навсегда — не перевыдаём при повторном входе
        else:
            role_name = assign_random_role(db_user['id'])
            logger.info("Пользователю %s назначена роль '%s'", member.id, role_name)

        lang = 'RU' if member.language_code == 'ru' else 'EN'
        mention = f'<a href="tg://user?id={member.id}">{member.full_name}</a>'
        text = message(lang, welcome_message, 'welcome')

        if role_name:
            text += message(lang, welcome_role_assigned, 'welcome', role_name)

        await update.message.reply_text(f'{mention}\n\n{text}', parse_mode='HTML')
        logger.info("Приветствие отправлено новому участнику %s в чате %s", member.id, chat_id)