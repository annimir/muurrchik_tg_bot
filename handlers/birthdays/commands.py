import logging
import re
from datetime import date

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import set_birthday, get_birthday, delete_birthday, get_user_language
from message.loader import message
from message.keys import (
    common_group_only, birthday_no_argument, birthday_no_correct,
    birthday_set, birthday_not_found, birthday_mine, birthday_deleted,
)

logger = logging.getLogger(__name__)

DATE_PATTERN = re.compile(r'^(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?$')


def _parse_date(raw: str):
    match = DATE_PATTERN.match(raw)
    if not match:
        return None
    day, month, year = match.groups()
    day, month = int(day), int(month)
    year = int(year) if year else None
    try:
        date(year or 2000, month, day)
    except ValueError:
        return None
    return day, month, year


async def _check_group(update: Update, lang: str) -> bool:
    if update.effective_chat.type not in ('group', 'supergroup'):
        await update.effective_message.reply_text(message(lang, common_group_only, 'common'))
        return False
    return True


async def set_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if not await _check_group(update, lang):
        return

    if not context.args:
        await update.effective_message.reply_text(message(lang, birthday_no_argument, 'birthday'))
        return

    parsed = _parse_date(context.args[0])
    if not parsed:
        logger.warning("Пользователь %s ввёл некорректную дату: %s", user.id, context.args[0])
        await update.effective_message.reply_text(message(lang, birthday_no_correct, 'birthday'))
        return

    day, month, year = parsed
    set_birthday(tg_id=user.id, tag=user.username or user.full_name, day=day, month=month, year=year)
    logger.info("Пользователь %s установил день рождения %02d.%02d", user.id, day, month)

    await update.effective_message.reply_text(message(lang, birthday_set, 'birthday', f'{day:02d}', f'{month:02d}'))


async def my_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if not await _check_group(update, lang):
        return

    row = get_birthday(user.id)
    if not row:
        await update.effective_message.reply_text(message(lang, birthday_not_found, 'birthday'))
        return

    await update.effective_message.reply_text(
        message(lang, birthday_mine, 'birthday', f'{row["day"]:02d}', f'{row["month"]:02d}')
    )


async def delete_birthday_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if not await _check_group(update, lang):
        return

    row = get_birthday(user.id)
    if not row:
        await update.effective_message.reply_text(message(lang, birthday_not_found, 'birthday'))
        return

    delete_birthday(user.id)
    logger.info("Пользователь %s удалил свой день рождения", user.id)
    await update.effective_message.reply_text(message(lang, birthday_deleted, 'birthday'))