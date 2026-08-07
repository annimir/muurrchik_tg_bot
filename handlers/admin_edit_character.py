import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import get_all_characters, update_character_field, get_user_language
from config import config
from message.loader import message
from message.keys import (
    common_private_only, assign_not_admin,
    edit_choose_character, edit_choose_field, edit_enter_value,
    edit_enter_photo, edit_photo_invalid, edit_saved,
    edit_field_name, edit_field_description, edit_field_affiliation,
    edit_field_position, edit_field_photo,
)
from services.admin import is_admin

logger = logging.getLogger(__name__)

CHOOSING_CHARACTER, CHOOSING_FIELD, WAITING_VALUE = range(3)

EDITABLE_FIELDS = {
    'name': edit_field_name,
    'description': edit_field_description,
    'affiliation': edit_field_affiliation,
    'position': edit_field_position,
}


def _admin_lang():
    return get_user_language(int(config.admin_user_id))


async def start_edit_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END

    if is_admin(update.effective_user.id):
        await update.message.reply_text(message(lang, assign_not_admin, 'assign'))
        return ConversationHandler.END

    characters = get_all_characters()
    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f'editchar:{c["id"]}')] for c in characters]
    await update.message.reply_text(message(lang, edit_choose_character, 'edit'), reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_CHARACTER


async def choose_character_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = _admin_lang()

    character_id = int(query.data.split(':')[1])
    context.user_data['editing_character_id'] = character_id

    keyboard = [
        [InlineKeyboardButton(message(lang, label_key, 'edit'), callback_data=f'field:{field}')]
        for field, label_key in EDITABLE_FIELDS.items()
    ]
    keyboard.append([InlineKeyboardButton(message(lang, edit_field_photo, 'edit'), callback_data='field:photo')])
    await query.edit_message_text(message(lang, edit_choose_field, 'edit'), reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_FIELD


async def choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = _admin_lang()

    field = query.data.split(':')[1]
    context.user_data['editing_field'] = field

    if field == 'photo':
        prompt = message(lang, edit_enter_photo, 'edit')
    else:
        label = message(lang, EDITABLE_FIELDS.get(field, edit_field_name), 'edit')
        prompt = message(lang, edit_enter_value, 'edit', label)

    await query.edit_message_text(prompt)
    return WAITING_VALUE


async def receive_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _admin_lang()
    character_id = context.user_data['editing_character_id']
    field = context.user_data['editing_field']

    if field == 'photo':
        if not update.message.photo:
            await update.message.reply_text(message(lang, edit_photo_invalid, 'edit'))
            return WAITING_VALUE
        value = update.message.photo[-1].file_id
        update_character_field(character_id, 'photo_file_id', value)
    else:
        value = update.message.text.strip()
        update_character_field(character_id, field, value)

    logger.info("Админ изменил поле '%s' персонажа #%d", field, character_id)
    await update.message.reply_text(message(lang, edit_saved, 'edit'))
    context.user_data.clear()
    return ConversationHandler.END