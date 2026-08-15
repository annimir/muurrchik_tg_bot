import logging
from datetime import date

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.queries import get_todays_birthdays, get_active_chats, get_user_language
from message.loader import message
from message.keys import birthday_congratulation_1, birthday_congratulation_2

logger = logging.getLogger(__name__)

CONGRATULATION_KEYS = [birthday_congratulation_1, birthday_congratulation_2]


async def check_birthdays(context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    birthdays = get_todays_birthdays(day=today.day, month=today.month)
    logger.info("Проверка дней рождения на %s: найдено %d записей", today.isoformat(), len(birthdays))

    if not birthdays:
        return

    active_chats = get_active_chats()
    if not active_chats:
        logger.warning("Нет активных чатов — поздравления отправить некуда")
        return
    if len(active_chats) > 1:
        logger.warning("Найдено несколько активных чатов (%d) — ожидался один; беру первый", len(active_chats))

    chat_id = active_chats[0]['chat_id']

    for row in birthdays:
        tg_id = row['tg_id']
        lang = get_user_language(tg_id)

        try:
            member = await context.bot.get_chat_member(chat_id, tg_id)
        except TelegramError as e:
            logger.warning("Не удалось проверить участника %s: %s", tg_id, e)
            continue

        if member.status in ('left', 'kicked'):
            continue

        mention = f'<a href="tg://user?id={tg_id}">{member.user.full_name}</a>'
        key = CONGRATULATION_KEYS[tg_id % len(CONGRATULATION_KEYS)]
        text = message(lang, key, 'birthday', mention)

        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
            logger.info("Поздравление отправлено пользователю %s", tg_id)
        except TelegramError as e:
            logger.error("Не удалось отправить поздравление в чат %s: %s", chat_id, e)