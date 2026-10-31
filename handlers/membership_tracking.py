import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import get_user_by_tg_id, upsert_membership, has_any_active_membership, mark_user_left_all

logger = logging.getLogger(__name__)


async def track_member_left(update: Update, context: ContextTypes.DEFAULT_TYPE):
    left_user = update.effective_message.left_chat_member
    if left_user is None or left_user.is_bot:
        return

    chat_id = update.effective_chat.id
    db_user = get_user_by_tg_id(left_user.id)
    if not db_user:
        return  # бот никогда не отслеживал этого пользователя — трекать нечего

    upsert_membership(db_user['id'], chat_id, is_member=False)

    if not has_any_active_membership(db_user['id']):
        mark_user_left_all(db_user['id'])
        logger.info("Пользователь %s покинул все известные боту чаты, начат отсчёт 6 месяцев", left_user.id)