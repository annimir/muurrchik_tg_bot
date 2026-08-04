import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_request_by_id, update_request_status, update_request_field,
    create_bot_character, link_user_character, count_user_characters, get_user_language,
)
from services.tag_storage import tag_storage
from config import config
from message.loader import message
from message.keys import (
    req_admin_already_resolved, req_admin_approved_suffix, req_admin_rejected_suffix,
    req_admin_max_characters_block, req_admin_choose_edit_field, req_admin_enter_new_value,
    req_admin_updated_preview, req_user_approved, req_user_rejected,
    req_admin_button_approve, req_admin_button_edit, req_admin_button_reject,
    edit_field_name, edit_field_description, edit_field_affiliation, edit_field_position,
)

logger = logging.getLogger(__name__)

EDITING_FIELD, EDITING_VALUE = range(2)

EDITABLE_FIELDS = {
    'name': edit_field_name,
    'description': edit_field_description,
    'affiliation': edit_field_affiliation,
    'position': edit_field_position,
}


def _admin_lang():
    return get_user_language(int(config.admin_user_id))


async def request_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if int(update.effective_user.id) != int(config.admin_user_id):
        return

    lang = _admin_lang()
    _, request_id, action = query.data.split(':')
    request_id = int(request_id)
    req = get_request_by_id(request_id)

    if not req or req['status'] != 'pending':
        await query.edit_message_caption(message(lang, req_admin_already_resolved, 'req'))
        return

    if action == 'approve':
        if count_user_characters(req['user_id']) >= 3:
            logger.warning("Заявка #%d заблокирована — у пользователя уже 3 персонажа", request_id)
            await query.message.reply_text(message(lang, req_admin_max_characters_block, 'req'))
            return

        await approve_request(context, req)
        await query.edit_message_caption(query.message.caption + message(lang, req_admin_approved_suffix, 'req'))

    elif action == 'reject':
        update_request_status(request_id, 'rejected')
        await notify_user_result(context, req, approved=False)
        await query.edit_message_caption(query.message.caption + message(lang, req_admin_rejected_suffix, 'req'))
        logger.info("Админ отклонил заявку #%d", request_id)

    elif action == 'edit':
        context.user_data['editing_request_id'] = request_id
        keyboard = [
            [InlineKeyboardButton(message(lang, label_key, 'edit'), callback_data=f'reqedit:{field}')]
            for field, label_key in EDITABLE_FIELDS.items()
        ]
        await query.message.reply_text(message(lang, req_admin_choose_edit_field, 'req'), reply_markup=InlineKeyboardMarkup(keyboard))
        return EDITING_FIELD


async def approve_request(context: ContextTypes.DEFAULT_TYPE, req: dict):
    character_id = create_bot_character(
        name=req['name'], description=req['description'],
        affiliation=req['affiliation'], position=req['position'],
        photo_file_id=req['photo_file_id'],
    )
    link_user_character(req['user_id'], character_id, assigned_by=config.admin_user_id)
    tag_storage.add_to_cache(req['name'])

    update_request_status(req['id'], 'approved')
    await notify_user_result(context, req, approved=True)
    logger.info("Админ одобрил заявку #%d, создан персонаж #%d", req['id'], character_id)


async def notify_user_result(context: ContextTypes.DEFAULT_TYPE, req: dict, approved: bool):
    from database.queries import get_user_by_id
    target_user = get_user_by_id(req['user_id'])
    lang = get_user_language(target_user['tg_id']) if target_user else 'RU'

    key = req_user_approved if approved else req_user_rejected
    text = message(lang, key, 'req', req['name'])

    await context.bot.send_message(chat_id=req['chat_id'], text=text)


async def choose_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = _admin_lang()
    field = query.data.split(':')[1]

    context.user_data['editing_field'] = field
    label = message(lang, EDITABLE_FIELDS[field], 'edit')
    await query.message.reply_text(message(lang, req_admin_enter_new_value, 'req', label))
    return EDITING_VALUE


async def receive_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _admin_lang()
    request_id = context.user_data['editing_request_id']
    field = context.user_data['editing_field']
    new_value = update.message.text.strip()

    update_request_field(request_id, field, new_value)
    logger.info("Админ изменил поле '%s' заявки #%d", field, request_id)

    req = get_request_by_id(request_id)
    keyboard = [
        [InlineKeyboardButton(message(lang, req_admin_button_approve, 'req'), callback_data=f'reqaction:{request_id}:approve')],
        [InlineKeyboardButton(message(lang, req_admin_button_edit, 'req'), callback_data=f'reqaction:{request_id}:edit')],
        [InlineKeyboardButton(message(lang, req_admin_button_reject, 'req'), callback_data=f'reqaction:{request_id}:reject')],
    ]
    await update.message.reply_text(
        message(lang, req_admin_updated_preview, 'req', req['name'], req['description'], req['affiliation'], req['position']),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    context.user_data.pop('editing_request_id', None)
    context.user_data.pop('editing_field', None)
    return ConversationHandler.END