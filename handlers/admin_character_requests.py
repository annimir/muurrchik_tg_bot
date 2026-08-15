import logging
import re
from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_character_request_by_id, update_character_request_status, update_character_request_field,
    is_character_name_taken, get_user_character_count, create_character_row, apply_character_edit,
    get_character_by_id, get_tag_by_name, create_tag, get_user_by_id, get_user_language,
)
from services.tag_storage import tag_storage
from services.admin import is_admin, admin_lang
from message.loader import message
from message.keys import (
    charreq_admin_already_resolved, charreq_admin_approved_suffix, charreq_admin_rejected_suffix,
    charreq_admin_max_block, charreq_admin_name_taken_block, charreq_admin_name_edit_taken,
    charreq_admin_choose_edit_field, charreq_admin_enter_new_value, charreq_admin_enter_new_photo,
    charreq_admin_updated_preview, charreq_edit_admin_updated_preview,
    charreq_admin_field_name, charreq_admin_field_birthdate, charreq_admin_field_description, charreq_admin_field_photo,
    charreq_photo_invalid, charreq_birthdate_invalid,
    charreq_admin_button_approve, charreq_admin_button_edit, charreq_admin_button_reject,
    charreq_user_approved, charreq_user_approved_primary, charreq_user_rejected,
    charreq_edit_user_approved, charreq_edit_user_rejected,
)

logger = logging.getLogger(__name__)

EDITING_FIELD, EDITING_VALUE = range(2)

CREATE_EDITABLE_FIELDS = {
    'name': charreq_admin_field_name,
    'birth_date': charreq_admin_field_birthdate,
    'description': charreq_admin_field_description,
    'photo_file_id': charreq_admin_field_photo,
}

EDIT_EDITABLE_FIELDS = {
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


async def _set_review_message(query, text: str):
    """
    ИСПРАВЛЕНО (сверка после D2b): заменяет ВЕСЬ текст итогового сообщения.
    Заявки на создание — всегда фото с caption (edit_message_caption),
    заявки на редактирование могут быть чистым текстом (edit_message_text).
    Используется, когда нет смысла что-то ДОписывать (например, заявка
    уже была обработана кем-то ещё до этого нажатия).
    """
    if query.message.photo:
        await query.edit_message_caption(text)
    else:
        await query.edit_message_text(text)


async def _append_to_review_message(query, suffix: str):
    """То же самое различение caption/text, но ДОписывает суффикс к уже
    существующему содержимому (для успешного approve/reject)."""
    if query.message.photo:
        await query.edit_message_caption(query.message.caption + suffix)
    else:
        await query.edit_message_text(query.message.text + suffix)


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
        # ИСПРАВЛЕНО: раньше здесь была строка с двумя `await` в одном
        # тернарном выражении (синтаксически рабочая, но плохо читаемая) —
        # теперь используется тот же хелпер, что и для остальных случаев.
        await _set_review_message(query, message(lang, charreq_admin_already_resolved, 'charreq'))
        return

    if action == 'approve':
        if req['request_type'] == 'create':
            if get_user_character_count(req['user_id']) >= 3:
                logger.warning("Заявка #%d заблокирована — у пользователя уже 3 персонажа", request_id)
                await query.message.reply_text(message(lang, charreq_admin_max_block, 'charreq'))
                return

            if is_character_name_taken(req['name']):
                logger.warning("Заявка #%d заблокирована — имя '%s' уже занято", request_id, req['name'])
                await query.message.reply_text(message(lang, charreq_admin_name_taken_block, 'charreq', req['name']))
                return

            await approve_character_create(context, req)
        else:
            await approve_character_edit_request(context, req)

        await _append_to_review_message(query, message(lang, charreq_admin_approved_suffix, 'charreq'))

    elif action == 'reject':
        update_character_request_status(request_id, 'rejected')
        await notify_character_request_result(context, req, approved=False)
        await _append_to_review_message(query, message(lang, charreq_admin_rejected_suffix, 'charreq'))
        logger.info("Админ отклонил заявку #%d (тип %s)", request_id, req['request_type'])

    elif action == 'edit':
        context.user_data['editing_charreq_id'] = request_id
        fields = CREATE_EDITABLE_FIELDS if req['request_type'] == 'create' else EDIT_EDITABLE_FIELDS
        keyboard = [
            [InlineKeyboardButton(message(lang, label_key, 'charreq'), callback_data=f'charreqedit:{field}')]
            for field, label_key in fields.items()
        ]
        await query.message.reply_text(message(lang, charreq_admin_choose_edit_field, 'charreq'), reply_markup=InlineKeyboardMarkup(keyboard))
        return EDITING_FIELD


async def approve_character_create(context, req):
    owner_user_id = req['user_id']
    is_primary = get_user_character_count(owner_user_id) == 0

    character = create_character_row(
        owner_user_id=owner_user_id, name=req['name'], birth_date=req['birth_date'],
        photo_file_id=req['photo_file_id'], description=req['description'], is_primary=is_primary,
    )

    existing_tag = get_tag_by_name(character['name'])
    if not existing_tag:
        owner = get_user_by_id(owner_user_id)
        create_tag(character['name'], created_by_tg_id=owner['tg_id'] if owner else None)
        tag_storage.add_to_cache(character['name'])
        logger.info("Автосоздан тег '%s' вместе с персонажем #%d (CHAR-07)", character['name'], character['id'])

    update_character_request_status(req['id'], 'approved')
    await notify_character_request_result(context, req, approved=True, is_primary=is_primary)
    logger.info("Админ одобрил заявку #%d, создан персонаж #%d (primary=%s)", req['id'], character['id'], is_primary)


async def approve_character_edit_request(context, req):
    apply_character_edit(
        req['character_id'],
        description=req['description'],
        photo_file_id=req['photo_file_id'],
        birth_date=req['birth_date'],
    )
    update_character_request_status(req['id'], 'approved')
    await notify_character_request_result(context, req, approved=True)
    logger.info("Админ одобрил заявку на изменение #%d (персонаж #%d)", req['id'], req['character_id'])


async def notify_character_request_result(context, req, approved: bool, is_primary: bool = False):
    target_user = get_user_by_id(req['user_id'])
    lang = get_user_language(target_user['tg_id']) if target_user else 'RU'

    if req['request_type'] == 'create':
        character_name = req['name']
        if approved:
            key = charreq_user_approved_primary if is_primary else charreq_user_approved
        else:
            key = charreq_user_rejected
    else:
        character = get_character_by_id(req['character_id'])
        character_name = character['name'] if character else '?'
        key = charreq_edit_user_approved if approved else charreq_edit_user_rejected

    text = message(lang, key, 'charreq', character_name)
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
        label_key = CREATE_EDITABLE_FIELDS.get(field, EDIT_EDITABLE_FIELDS.get(field))
        label = message(lang, label_key, 'charreq')
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
    logger.info("Админ изменил поле '%s' заявки #%d", field, request_id)

    req = get_character_request_by_id(request_id)
    keyboard = [
        [InlineKeyboardButton(message(lang, charreq_admin_button_approve, 'charreq'), callback_data=f'charreqaction:{request_id}:approve')],
        [InlineKeyboardButton(message(lang, charreq_admin_button_edit, 'charreq'), callback_data=f'charreqaction:{request_id}:edit')],
        [InlineKeyboardButton(message(lang, charreq_admin_button_reject, 'charreq'), callback_data=f'charreqaction:{request_id}:reject')],
    ]

    if req['request_type'] == 'create':
        birth_str = req['birth_date'].strftime('%d.%m') if req['birth_date'] else '—'
        preview = message(lang, charreq_admin_updated_preview, 'charreq', req['name'], birth_str, req['description'])
    else:
        preview = message(lang, charreq_edit_admin_updated_preview, 'charreq')

    await update.message.reply_text(preview, reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data.pop('editing_charreq_id', None)
    context.user_data.pop('editing_charreq_field', None)
    return ConversationHandler.END