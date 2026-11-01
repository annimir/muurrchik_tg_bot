import html
import logging
from datetime import date

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.queries import get_todays_character_birthdays, get_active_chats, get_user_language
from message.loader import message
from message.keys import charbday_congratulation_1, charbday_congratulation_2

logger = logging.getLogger(__name__)

CONGRATULATION_KEYS = [charbday_congratulation_1, charbday_congratulation_2]


async def check_character_birthdays(context: ContextTypes.DEFAULT_TYPE):
    today = date.today()
    birthdays = get_todays_character_birthdays(day=today.day, month=today.month)
    logger.info("Проверка дней рождения персонажей на %s: найдено %d", today.isoformat(), len(birthdays))

    if not birthdays:
        return

    active_chats = get_active_chats()
    if not active_chats:
        logger.warning("Нет активных чатов — поздравления персонажей отправить некуда")
        return
    if len(active_chats) > 1:
        # бот спроектирован под один чат (см. решения по Этапу 4 первого раунда) —
        # если вдруг активных чатов больше, берём первый и громко логируем,
        # а не падаем и не рассылаем во все сразу молча
        logger.warning("Найдено несколько активных чатов (%d) — ожидался один; беру первый", len(active_chats))

    chat_id = active_chats[0]['chat_id']

    for row in birthdays:
        owner_tg_id = row['owner_tg_id']
        lang = get_user_language(owner_tg_id)

        try:
            member = await context.bot.get_chat_member(chat_id, owner_tg_id)
        except TelegramError as e:
            logger.warning("Не удалось проверить владельца %s персонажа '%s': %s", owner_tg_id, row['name'], e)
            continue

        if member.status in ('left', 'kicked'):
            logger.info("Владелец персонажа '%s' покинул чат, поздравление пропущено", row['name'])
            continue

        display_name = html.escape(member.user.full_name, quote=False)
        character_name = html.escape(row['name'], quote=False)
        mention = f'<a href="tg://user?id={owner_tg_id}">{display_name}</a>'
        key = CONGRATULATION_KEYS[row['id'] % len(CONGRATULATION_KEYS)]
        text = message(lang, key, 'charbday', character_name, mention)

        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode='HTML')
            logger.info("Поздравление с ДР персонажа '%s' отправлено (владелец %s)", row['name'], owner_tg_id)
        except TelegramError as e:
            logger.error("Не удалось отправить поздравление персонажа '%s': %s", row['name'], e)