import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import get_user_by_tg_id, create_user, get_user_characters, set_character_primary, \
    get_user_language
from services.admin import is_admin
from message.loader import message
from message.keys import (
    common_private_only, common_not_admin,
    charprimary_admin_forward_prompt, charprimary_admin_forward_invalid,
    charprimary_admin_no_characters, charprimary_admin_choose, charprimary_admin_done,
)

logger = logging.getLogger(__name__)

WAITING_FORWARD, CHOOSING_CHARACTER = range(2)


async def start_admin_setprimary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    await update.effective_message.reply_text(message(lang, charprimary_admin_forward_prompt, 'charprimary'))
    return WAITING_FORWARD


async def receive_admin_setprimary_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    origin = update.effective_message.forward_origin

    if origin is None or origin.type != 'user':
        await update.effective_message.reply_text(message(lang, charprimary_admin_forward_invalid, 'charprimary'))
        return WAITING_FORWARD

    target_user = origin.sender_user
    db_user = get_user_by_tg_id(target_user.id)
    if not db_user:
        create_user(target_user.id, target_user.username or target_user.full_name)
        db_user = get_user_by_tg_id(target_user.id)

    characters = get_user_characters(db_user['id'])
    if not characters:
        await update.effective_message.reply_text(message(lang, charprimary_admin_no_characters, 'charprimary'))
        return ConversationHandler.END

    context.user_data['admin_setprimary_target'] = {
        'user_id': db_user['id'], 'tg_id': target_user.id, 'name': target_user.full_name,
    }

    keyboard = [
        [InlineKeyboardButton(('⭐ ' if c['is_primary'] else '') + c['name'], callback_data=f'adminsetprimary:{c["id"]}')]
        for c in characters
    ]
    await update.effective_message.reply_text(
        message(lang, charprimary_admin_choose, 'charprimary', target_user.full_name),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING_CHARACTER


async def admin_setprimary_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    lang = get_user_language(update.effective_user.id)
    data = context.user_data.get('admin_setprimary_target')
    if not data:
        return ConversationHandler.END

    character_id = int(query.data.split(':')[1])
    characters = get_user_characters(data['user_id'])
    target_character = next((c for c in characters if c['id'] == character_id), None)

    if not target_character:
        logger.warning("Админ пытался выбрать несуществующего персонажа %s для пользователя %s", character_id, data['tg_id'])
        return ConversationHandler.END

    set_character_primary(data['user_id'], character_id)
    logger.info("Админ сменил основного персонажа пользователя %s на #%d", data['tg_id'], character_id)

    await query.edit_message_text(
        message(lang, charprimary_admin_done, 'charprimary', data['name'], target_character['name'])
    )
    context.user_data.pop('admin_setprimary_target', None)
    return ConversationHandler.END