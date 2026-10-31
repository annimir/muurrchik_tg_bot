import logging

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.queries import (
    get_users_pending_warning, get_users_pending_deletion,
    mark_user_warned, delete_user_completely,
)
from message.loader import message
from message.keys import retention_warning_message

logger = logging.getLogger(__name__)


async def send_retention_warnings(context: ContextTypes.DEFAULT_TYPE):
    users = get_users_pending_warning()
    logger.info("Найдено %d пользователей для предупреждения об удалении", len(users))

    for user in users:
        lang = user.get('language') or 'RU'
        text = message(lang, retention_warning_message, 'retention')

        try:
            await context.bot.send_message(chat_id=user['tg_id'], text=text)
        except TelegramError as e:
            logger.warning("Не удалось отправить предупреждение пользователю %s: %s", user['tg_id'], e)
            continue

        mark_user_warned(user['id'])
        logger.info("Предупреждение об удалении отправлено пользователю %s", user['tg_id'])


async def run_retention_cleanup(context: ContextTypes.DEFAULT_TYPE):
    users = get_users_pending_deletion()
    logger.info("Найдено %d пользователей для удаления по истечении срока неактивности", len(users))

    for user in users:
        delete_user_completely(user['id'])
        logger.info("Пользователь %s удалён из БД (неактивен 6+ месяцев, предупреждение было отправлено)", user['tg_id'])