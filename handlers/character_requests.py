import logging
import re
from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_user_by_tg_id, get_user_character_count, is_character_name_taken,
    create_character_request, get_user_character_requests, get_character_by_id, get_user_language, get_all_admin_ids,
)
from message.loader import message
from message.keys import (
    charreq_limit_warning, charreq_ask_name, charreq_name_taken, charreq_ask_birthdate,
    charreq_birthdate_invalid, charreq_ask_description, charreq_ask_photo, charreq_photo_invalid,
    charreq_submitted, charreq_cancelled,
    charreq_my_empty, charreq_my_type_create, charreq_my_type_edit,
    charreq_my_status_pending, charreq_my_status_approved, charreq_my_status_rejected,
)

logger = logging.getLogger(__name__)

ASK_NAME, ASK_BIRTHDATE, ASK_DESCRIPTION, ASK_PHOTO = range(4)

DATE_PATTERN = re.compile(r'^(\d{1,2})\.(\d{1,2})$')
PLACEHOLDER_YEAR = 2000


def _parse_birthdate(raw: str):
    match = DATE_PATTERN.match(raw.strip())
    if not match:
        return None
    day, month = int(match.group(1)), int(match.group(2))
    try:
        return date(PLACEHOLDER_YEAR, month, day)
    except ValueError:
        return None


async def start_character_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    db_user = get_user_by_tg_id(user.id)
    if db_user and get_user_character_count(db_user['id']) >= 3:
        await update.message.reply_text(message(lang, charreq_limit_warning, 'charreq'))

    context.user_data['charreq'] = {'origin_chat_id': update.effective_chat.id}
    await update.message.reply_text(message(lang, charreq_ask_name, 'charreq'))
    return ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    name = update.message.text.strip()

    if is_character_name_taken(name):
        await update.message.reply_text(message(lang, charreq_name_taken, 'charreq', name))
        return ASK_NAME

    context.user_data['charreq']['name'] = name
    await update.message.reply_text(message(lang, charreq_ask_birthdate, 'charreq'))
    return ASK_BIRTHDATE


async def ask_birthdate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    parsed = _parse_birthdate(update.message.text)

    if not parsed:
        await update.message.reply_text(message(lang, charreq_birthdate_invalid, 'charreq'))
        return ASK_BIRTHDATE

    context.user_data['charreq']['birth_date'] = parsed
    await update.message.reply_text(message(lang, charreq_ask_description, 'charreq'))
    return ASK_DESCRIPTION


async def ask_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data['charreq']['description'] = update.message.text.strip()
    await update.message.reply_text(message(lang, charreq_ask_photo, 'charreq'))
    return ASK_PHOTO


async def ask_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)

    if not update.message.photo:
        await update.message.reply_text(message(lang, charreq_photo_invalid, 'charreq'))
        return ASK_PHOTO

    photo_file_id = update.message.photo[-1].file_id
    data = context.user_data['charreq']

    user = update.effective_user
    db_user = get_user_by_tg_id(user.id)

    request_id = create_character_request(
        request_type='create',
        user_id=db_user['id'],
        chat_id=data['origin_chat_id'],
        name=data['name'],
        birth_date=data['birth_date'],
        description=data['description'],
        photo_file_id=photo_file_id,
        requester_display_name=user.full_name,
        requester_username=user.username,
    )

    logger.info("Пользователь %s подал заявку #%d на персонажа '%s'", user.id, request_id, data['name'])
    await update.message.reply_text(message(lang, charreq_submitted, 'charreq'))

    await notify_admin_new_character_request(context, request_id)  # ИЗМЕНЕНО: без data/user
    context.user_data.pop('charreq', None)
    return ConversationHandler.END


async def notify_admin_new_character_request(context, request_id):
    """
    ПЕРЕПИСАНО: теперь единая функция для ОБОИХ типов заявок (create и edit) —
    именно её отсутствие в character_edit.py и было причиной бага 1.
    character_edit.py импортирует и вызывает эту же функцию, а не свою копию.
    """
    from database.queries import get_character_request_by_id
    from handlers.admin_character_requests import _build_character_request_content
    from services.request_broadcast import broadcast_to_admins
    from message.keys import req_claim_button

    req = get_character_request_by_id(request_id)

    async def send_fn(admin_tg_id):
        admin_lang_value = get_user_language(admin_tg_id)
        content, photo = _build_character_request_content(req, admin_lang_value)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(message(admin_lang_value, req_claim_button, 'reqclaim'), callback_data=f'charreqaction:{request_id}:claim'),
        ]])
        if photo:
            return await context.bot.send_photo(admin_tg_id, photo=photo, caption=content, parse_mode='Markdown', reply_markup=keyboard)
        return await context.bot.send_message(admin_tg_id, text=content, parse_mode='Markdown', reply_markup=keyboard)

    await broadcast_to_admins(context, 'character', request_id, send_fn)

async def cancel_character_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data.pop('charreq', None)
    await update.message.reply_text(message(lang, charreq_cancelled, 'charreq'))
    return ConversationHandler.END


async def my_character_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ДОБАВЛЕНО: /mycharrequests — просмотр своих заявок (create и edit вперемешку)."""
    user = update.effective_user
    lang = get_user_language(user.id)

    db_user = get_user_by_tg_id(user.id)
    requests = get_user_character_requests(db_user['id']) if db_user else []

    if not requests:
        await update.message.reply_text(message(lang, charreq_my_empty, 'charreq'))
        return

    type_labels = {'create': charreq_my_type_create, 'edit': charreq_my_type_edit}
    status_labels = {
        'pending': charreq_my_status_pending,
        'approved': charreq_my_status_approved,
        'rejected': charreq_my_status_rejected,
    }

    lines = []
    for req in requests:
        if req['request_type'] == 'create':
            character_name = req['name']
        else:
            character = get_character_by_id(req['character_id'])
            character_name = character['name'] if character else '?'

        type_label = message(lang, type_labels[req['request_type']], 'charreq')
        status_label = message(lang, status_labels.get(req['status'], charreq_my_status_pending), 'charreq')
        lines.append(f'{character_name} ({type_label}) — {status_label}')

    await update.message.reply_text('\n'.join(lines))