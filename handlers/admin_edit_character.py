# handlers/admin_edit_character.py
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import get_all_characters, get_character_by_id, update_character_field
from config import config

logger = logging.getLogger(__name__)

CHOOSING_CHARACTER, CHOOSING_FIELD, WAITING_VALUE = range(3)

EDITABLE_FIELDS = {
    'name': 'Имя', 'description': 'Описание',
    'affiliation': 'Принадлежность', 'position': 'Должность',
}


async def start_edit_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private' or int(update.effective_user.id) != int(config.admin_user_id):
        return ConversationHandler.END

    characters = get_all_characters()
    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f'editchar:{c["id"]}')] for c in characters]
    await update.message.reply_text('Кого редактируем?', reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_CHARACTER


async def choose_character_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    character_id = int(query.data.split(':')[1])
    context.user_data['editing_character_id'] = character_id

    keyboard = [[InlineKeyboardButton(label, callback_data=f'field:{f}')] for f, label in EDITABLE_FIELDS.items()]
    keyboard.append([InlineKeyboardButton('📷 Фото', callback_data='field:photo')])
    await query.edit_message_text('Что меняем?', reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_FIELD


async def choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    field = query.data.split(':')[1]
    context.user_data['editing_field'] = field

    prompt = 'Пришлите новое фото:' if field == 'photo' else f'Введите новое значение для «{EDITABLE_FIELDS.get(field, field)}»:'
    await query.edit_message_text(prompt)
    return WAITING_VALUE


async def receive_new_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    character_id = context.user_data['editing_character_id']
    field = context.user_data['editing_field']

    if field == 'photo':
        if not update.message.photo:
            await update.message.reply_text('Пришлите именно фото.')
            return WAITING_VALUE
        value = update.message.photo[-1].file_id
        update_character_field(character_id, 'photo_file_id', value)
    else:
        value = update.message.text.strip()
        update_character_field(character_id, field, value)

    logger.info("Админ изменил поле '%s' персонажа #%d", field, character_id)
    await update.message.reply_text('Готово! Изменения сохранены.')
    context.user_data.clear()
    return ConversationHandler.END