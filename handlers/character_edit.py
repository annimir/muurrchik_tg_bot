import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_user_by_tg_id, get_user_characters, get_character_by_id,
    create_character_request, get_user_language,
)
from handlers.character_requests import notify_admin_new_character_request
from services.validation import MAX_TEXT_LENGTH, text_is_too_long
from message.loader import message
from message.keys import (
    charedit_no_characters, charedit_not_owner, charedit_choose_character, charedit_choose_field,
    charedit_field_description, charedit_field_photo, charedit_enter_description, charedit_enter_photo,
    charedit_submitted, charreq_photo_invalid, charreq_cancelled,
)

logger = logging.getLogger(__name__)

CHOOSE_CHARACTER, CHOOSE_FIELD, WAITING_VALUE = range(3)


def _field_keyboard(lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(message(lang, charedit_field_description, 'charedit'), callback_data='editcharfield:description')],
        [InlineKeyboardButton(message(lang, charedit_field_photo, 'charedit'), callback_data='editcharfield:photo')],
    ])


async def start_character_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    db_user = get_user_by_tg_id(user.id)
    characters = get_user_characters(db_user['id']) if db_user else []

    if not characters:
        await update.effective_message.reply_text(message(lang, charedit_no_characters, 'charedit'))
        return ConversationHandler.END

    if len(characters) == 1:
        context.user_data['charedit'] = {'character_id': characters[0]['id'], 'character_name': characters[0]['name']}
        await update.effective_message.reply_text(message(lang, charedit_choose_field, 'charedit'), reply_markup=_field_keyboard(lang))
        return CHOOSE_FIELD

    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f'editcharpick:{c["id"]}')] for c in characters]
    await update.effective_message.reply_text(message(lang, charedit_choose_character, 'charedit'), reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSE_CHARACTER


async def pick_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = get_user_language(user.id)
    character_id = int(query.data.split(':')[1])

    character = get_character_by_id(character_id)
    db_user = get_user_by_tg_id(user.id)

    if not character or not db_user or character['owner_user_id'] != db_user['id']:
        logger.warning("Пользователь %s попытался редактировать чужого/несуществующего персонажа %s", user.id, character_id)
        await query.edit_message_text(message(lang, charedit_not_owner, 'charedit'))
        return ConversationHandler.END

    context.user_data['charedit'] = {'character_id': character['id'], 'character_name': character['name']}
    await query.edit_message_text(message(lang, charedit_choose_field, 'charedit'), reply_markup=_field_keyboard(lang))
    return CHOOSE_FIELD


async def choose_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    field = query.data.split(':')[1]
    context.user_data['charedit']['field'] = field

    prompt_key = charedit_enter_description if field == 'description' else charedit_enter_photo
    await query.edit_message_text(message(lang, prompt_key, 'charedit'))
    return WAITING_VALUE


async def receive_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)
    data = context.user_data.get('charedit')

    if not data:
        return ConversationHandler.END

    field = data['field']

    if field == 'photo':
        if not update.effective_message.photo:
            await update.effective_message.reply_text(message(lang, charreq_photo_invalid, 'charreq'))
            return WAITING_VALUE
        photo_file_id = update.effective_message.photo[-1].file_id
        description = None
    else:
        description = update.effective_message.text.strip()
        if text_is_too_long(description):
            await update.effective_message.reply_text(
                message(lang, 'common.textTooLong', 'common', MAX_TEXT_LENGTH)
            )
            return WAITING_VALUE
        photo_file_id = None

    db_user = get_user_by_tg_id(user.id)
    request_id = create_character_request(
        request_type='edit',
        user_id=db_user['id'],
        chat_id=update.effective_chat.id,
        character_id=data['character_id'],
        description=description,
        photo_file_id=photo_file_id,
        requester_display_name=user.full_name,  # ДОБАВЛЕНО — тоже было упущено в D2b
        requester_username=user.username,  # ДОБАВЛЕНО
    )

    logger.info(
        "Пользователь %s подал заявку на изменение персонажа #%d (поле %s)",
        user.id, data['character_id'], field,
    )
    await update.effective_message.reply_text(message(lang, charedit_submitted, 'charedit'))

    await notify_admin_new_character_request(context, request_id)  # используем общую функцию
    context.user_data.pop('charedit', None)
    return ConversationHandler.END

async def cancel_character_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data.pop('charedit', None)
    await update.effective_message.reply_text(message(lang, charreq_cancelled, 'charreq'))
    return ConversationHandler.END