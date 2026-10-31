import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_all_flavor_roles, get_flavor_role_by_id,
    update_flavor_role_photo, update_flavor_role_description, update_flavor_role_wiki_url,
    get_user_language,
)
from services.admin import is_admin
from services.validation import MAX_TEXT_LENGTH, text_is_too_long
from message.loader import message
from message.keys import (
    common_private_only, common_not_admin,
    roleedit_no_roles, roleedit_choose_role, roleedit_choose_field,
    roleedit_field_photo, roleedit_field_description, roleedit_field_wiki,
    roleedit_enter_photo, roleedit_enter_description, roleedit_enter_wiki,
    roleedit_photo_invalid, roleedit_wiki_invalid, roleedit_saved,
)

logger = logging.getLogger(__name__)

CHOOSING_ROLE, CHOOSING_FIELD, WAITING_VALUE = range(3)

FIELD_LABELS = {
    'photo': roleedit_field_photo,
    'description': roleedit_field_description,
    'wiki_url': roleedit_field_wiki,
}


async def start_edit_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    roles = get_all_flavor_roles()
    if not roles:
        await update.effective_message.reply_text(message(lang, roleedit_no_roles, 'roleedit'))
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(r['name'], callback_data=f'roleeditpick:{r["id"]}')] for r in roles]
    await update.effective_message.reply_text(message(lang, roleedit_choose_role, 'roleedit'), reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_ROLE


async def choose_role_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    role_id = int(query.data.split(':')[1])
    context.user_data['editing_role_id'] = role_id

    keyboard = [
        [InlineKeyboardButton(message(lang, label_key, 'roleedit'), callback_data=f'roleeditfield:{field}')]
        for field, label_key in FIELD_LABELS.items()
    ]
    await query.edit_message_text(message(lang, roleedit_choose_field, 'roleedit'), reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_FIELD


async def choose_role_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    field = query.data.split(':')[1]
    context.user_data['editing_role_field'] = field

    prompt_key = {
        'photo': roleedit_enter_photo,
        'description': roleedit_enter_description,
        'wiki_url': roleedit_enter_wiki,
    }[field]
    await query.edit_message_text(message(lang, prompt_key, 'roleedit'))
    return WAITING_VALUE


async def receive_role_field_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    role_id = context.user_data['editing_role_id']
    field = context.user_data['editing_role_field']

    if field == 'photo':
        if not update.effective_message.photo:
            await update.effective_message.reply_text(message(lang, roleedit_photo_invalid, 'roleedit'))
            return WAITING_VALUE
        update_flavor_role_photo(role_id, update.effective_message.photo[-1].file_id)

    elif field == 'wiki_url':
        url = update.effective_message.text.strip()
        if not (url.startswith('http://') or url.startswith('https://')):
            await update.effective_message.reply_text(message(lang, roleedit_wiki_invalid, 'roleedit'))
            return WAITING_VALUE
        update_flavor_role_wiki_url(role_id, url)

    else:
        description = update.effective_message.text.strip()
        if text_is_too_long(description):
            await update.effective_message.reply_text(
                message(lang, 'common.textTooLong', 'common', MAX_TEXT_LENGTH)
            )
            return WAITING_VALUE
        update_flavor_role_description(role_id, description)

    logger.info("Админ %s изменил поле '%s' роли #%d", update.effective_user.id, field, role_id)

    role = get_flavor_role_by_id(role_id)
    await update.effective_message.reply_text(message(lang, roleedit_saved, 'roleedit', role['name']))
    context.user_data.pop('editing_role_id', None)
    context.user_data.pop('editing_role_field', None)
    return ConversationHandler.END