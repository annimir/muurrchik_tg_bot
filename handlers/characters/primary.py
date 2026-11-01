import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.queries import get_user_by_tg_id, get_user_characters, set_character_primary, get_user_language
from message.loader import message
from message.keys import charprimary_no_characters, charprimary_only_one, charprimary_choose, charprimary_done

logger = logging.getLogger(__name__)


async def setprimary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    db_user = get_user_by_tg_id(user.id)
    characters = get_user_characters(db_user['id']) if db_user else []

    if not characters:
        await update.effective_message.reply_text(message(lang, charprimary_no_characters, 'charprimary'))
        return

    if len(characters) == 1:
        await update.effective_message.reply_text(message(lang, charprimary_only_one, 'charprimary'))
        return

    keyboard = [
        [InlineKeyboardButton(('⭐ ' if c['is_primary'] else '') + c['name'], callback_data=f'setprimary:{c["id"]}')]
        for c in characters
    ]
    await update.effective_message.reply_text(
        message(lang, charprimary_choose, 'charprimary'), reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def setprimary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = get_user_language(user.id)
    character_id = int(query.data.split(':')[1])

    db_user = get_user_by_tg_id(user.id)
    characters = get_user_characters(db_user['id']) if db_user else []
    # владение проверяется самим фактом, что character_id ищется ТОЛЬКО
    # среди персонажей, полученных по owner_user_id этого же пользователя —
    # чужой id просто не найдётся в списке
    target = next((c for c in characters if c['id'] == character_id), None)

    if not target:
        logger.warning("Пользователь %s пытался выбрать чужого/несуществующего персонажа основным (%s)", user.id, character_id)
        return

    set_character_primary(db_user['id'], character_id)
    logger.info("Пользователь %s сменил основного персонажа на #%d", user.id, character_id)
    await query.edit_message_text(message(lang, charprimary_done, 'charprimary', target['name']))