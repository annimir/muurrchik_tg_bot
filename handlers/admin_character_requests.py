import logging
import re
from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_character_request_by_id, update_character_request_status, update_character_request_field,
    is_character_name_taken, get_user_character_count, create_character_row,
    get_tag_by_name, create_tag, get_user_by_id, get_user_language,
)
from services.tag_storage import tag_storage
from services.admin import is_admin, admin_lang
from message.loader import message
from message.keys import (
    charreq_admin_already_resolved, charreq_admin_approved_suffix, charreq_admin_rejected_suffix,
    charreq_admin_max_block, charreq_admin_name_taken_block, charreq_admin_name_edit_taken,
    charreq_admin_choose_edit_field, charreq_admin_enter_new_value, charreq_admin_enter_new_photo,
    charreq_admin_updated_preview, charreq_admin_field_name, charreq_admin_field_birthdate,
    charreq_admin_field_description, charreq_admin_field_photo, charreq_photo_invalid, charreq_birthdate_invalid,
    charreq_admin_button_approve, charreq_admin_button_edit, charreq_admin_button_reject,
    charreq_user_approved, charreq_user_approved_primary, charreq_user_rejected,
)

logger = logging.getLogger(__name__)

EDITING_FIELD, EDITING_VALUE = range(2)

EDITABLE_FIELDS = {
    'name': charreq_admin_field_name,
    'birth_date': charreq_admin_field_birthdate,
    'description': charreq_admin_field_description,
    'photo_file_id': charreq_admin_field_photo,
}

DATE_PATTERN = re.compile(r'^(\d{1,2})\.(\d{1,2})$')


def _parse_birthdate(raw: str):
    match = DATE_PATTERN.match(raw.strip())
    if not match:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    try:
        return date(2000, month, day)
    except ValueError:
        return None


async def character_request_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        return

    lang = admin_lang()
    _, request_id, action = query.data.split(':')
    request_id = int(request_id)
    req = get_character_request_by_id(request_id)

    if not req or req['status'] != 'pending':
        await query.edit_message_caption(message(lang, charreq_admin_already_resolved, 'charreq'))
        return

    if action == 'approve':
        if get_user_character_count(req['user_id']) >= 3:
            logger.warning("Заявка #%d заблокирована — у пользователя уже 3 персонажа", request_id)
            await query.message.reply_text(message(lang, charreq_admin_max_block, 'charreq'))
            return

        if is_character_name_taken(req['name']):
            logger.warning("Заявка #%d заблокирована — имя '%s' уже занято", request_id, req['name'])
            await query.message.reply_text(message(lang, charreq_admin_name_taken_block, 'charreq', req['name']))
            return

        await approve_character_request(context, req)
        await query.edit_message_caption(query.message.caption + message(lang, charreq_admin_approved_suffix, 'charreq'))

    elif action == 'reject':
        update_character_request_status(request_id, 'rejected')
        await notify_character_request_result(context, req, approved=False)
        await query.edit_message_caption(query.message.caption + message(lang, charreq_admin_rejected_suffix, 'charreq'))
        logger.info("Админ отклонил заявку на персонажа #%d", request_id)

    elif action == 'edit':
        context.user_data['editing_charreq_id'] = request_id
        keyboard = [
            [InlineKeyboardButton(message(lang, label_key, 'charreq'), callback_data=f'charreqedit:{field}')]
            for field, label_key in EDITABLE_FIELDS.items()
        ]
        await query.message.reply_text(message(lang, charreq_admin_choose_edit_field, 'charreq'), reply_markup=InlineKeyboardMarkup(keyboard))
        return EDITING_FIELD


async def approve_character_request(context, req):
    owner_user_id = req['user_id']
    is_primary = get_user_character_count(owner_user_id) == 0

    character = create_character_row(
        owner_user_id=owner_user_id, name=req['name'], birth_date=req['birth_date'],
        photo_file_id=req['photo_file_id'], description=req['description'], is_primary=is_primary,
    )

    # CHAR-07: автосоздание TAG с тем же именем, если его ещё нет
    existing_tag = get_tag_by_name(character['name'])
    if not existing_tag:
        owner = get_user_by_id(owner_user_id)
        create_tag(character['name'], created_by_tg_id=owner['tg_id'] if owner else None)
        tag_storage.add_to_cache(character['name'])
        logger.info("Автосоздан тег '%s' вместе с персонажем #%d (CHAR-07)", character['name'], character['id'])

    update_character_request_status(req['id'], 'approved')
    await notify_character_request_result(context, req, approved=True, is_primary=is_primary)
    logger.info("Админ одобрил заявку #%d, создан персонаж #%d (primary=%s)", req['id'], character['id'], is_primary)


async def notify_character_request_result(context, req, approved: bool, is_primary: bool = False):
    target_user = get_user_by_id(req['user_id'])
    lang = get_user_language(target_user['tg_id']) if target_user else 'RU'

    if approved:
        key = charreq_user_approved_primary if is_primary else charreq_user_approved
        text = message(lang, key, 'charreq', req['name'])
    else:
        text = message(lang, charreq_user_rejected, 'charreq', req['name'])

    await context.bot.send_message(chat_id=req['chat_id'], text=text)


async def choose_charreq_edit_field(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = admin_lang()
    field = query.data.split(':')[1]

    context.user_data['editing_charreq_field'] = field
    if field == 'photo_file_id':
        await query.message.reply_text(message(lang, charreq_admin_enter_new_photo, 'charreq'))
    else:
        label = message(lang, EDITABLE_FIELDS[field], 'charreq')
        await query.message.reply_text(message(lang, charreq_admin_enter_new_value, 'charreq', label))
    return EDITING_VALUE


async def receive_charreq_edit_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()
    request_id = context.user_data['editing_charreq_id']
    field = context.user_data['editing_charreq_field']

    if field == 'photo_file_id':
        if not update.message.photo:
            await update.message.reply_text(message(lang, charreq_photo_invalid, 'charreq'))
            return EDITING_VALUE
        value = update.message.photo[-1].file_id

    elif field == 'birth_date':
        parsed = _parse_birthdate(update.message.text)
        if not parsed:
            await update.message.reply_text(message(lang, charreq_birthdate_invalid, 'charreq'))
            return EDITING_VALUE
        value = parsed

    elif field == 'name':
        value = update.message.text.strip()
        if is_character_name_taken(value):
            await update.message.reply_text(message(lang, charreq_admin_name_edit_taken, 'charreq', value))
            return EDITING_VALUE

    else:
        value = update.message.text.strip()

    update_character_request_field(request_id, field, value)
    logger.info("Админ изменил поле '%s' заявки на персонажа #%d", field, request_id)

    req = get_character_request_by_id(request_id)
    keyboard = [
        [InlineKeyboardButton(message(lang, charreq_admin_button_approve, 'charreq'), callback_data=f'charreqaction:{request_id}:approve')],
        [InlineKeyboardButton(message(lang, charreq_admin_button_edit, 'charreq'), callback_data=f'charreqaction:{request_id}:edit')],
        [InlineKeyboardButton(message(lang, charreq_admin_button_reject, 'charreq'), callback_data=f'charreqaction:{request_id}:reject')],
    ]
    birth_str = req['birth_date'].strftime('%d.%m') if req['birth_date'] else '—'
    await update.message.reply_text(
        message(lang, charreq_admin_updated_preview, 'charreq', req['name'], birth_str, req['description']),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    context.user_data.pop('editing_charreq_id', None)
    context.user_data.pop('editing_charreq_field', None)
    return ConversationHandler.END