import logging
from datetime import date

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.queries import get_todays_birthdays, get_user_language
from message.loader import message
from message.keys import birthday_congratulation_1, birthday_congratulation_2

logger = logging.getLogger(__name__)
CONGRATULATION_KEYS = [birthday_congratulation_1, birthday_congratulation_2]

async def check_birthdays(context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    birthdays = get_todays_birthdays(day=today.day, month=today.month)
    logger.info("Проверка дней рождения на %s: найдено %d записей", today.isoformat(), len(birthdays))

    for row in birthdays:
        tg_id = row['tg_id']
        chat_id = row['chat_id']
        lang = get_user_language(tg_id)

        try:
            member = await context.bot.get_chat_member(chat_id, tg_id)
        except TelegramError as e:
            logger.warning("Не удалось проверить участника %s в чате %s: %s", tg_id, chat_id, e)
            continue

        if member.status in ('left', 'kicked'):
            logger.info("Пользователь %s покинул чат %s, поздравление пропущено", tg_id, chat_id)
            continue

        mention = f'<a href="tg://user?id={tg_id}">{member.user.full_name}</a>'
        key = CONGRATULATION_KEYS[tg_id % len(CONGRATULATION_KEYS)]
        text = message(lang, key, 'birthday', mention)

        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
            logger.info("Поздравление отправлено пользователю %s в чате %s", tg_id, chat_id)
        except TelegramError as e:
            logger.error("Не удалось отправить поздравление в чат %s: %s", chat_id, e)