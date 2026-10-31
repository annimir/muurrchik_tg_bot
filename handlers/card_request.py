import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import get_user_by_tg_id, create_card_request, get_user_card_requests, get_user_language, \
    get_all_admin_ids
from config import config
from services.auth import auth
from services.validation import MAX_TEXT_LENGTH, text_is_too_long
from message.loader import message
from message.keys import (
    cardreq_ask_bio, cardreq_submitted, cardreq_cancelled,
    cardreq_admin_notification, cardreq_admin_button_approve, cardreq_admin_button_edit, cardreq_admin_button_reject,
    cardreq_my_empty, cardreq_my_status_pending, cardreq_my_status_approved, cardreq_my_status_rejected,
)

logger = logging.getLogger(__name__)

WAITING_BIO = range(1)[0]


async def start_card_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data['cardreq_chat_id'] = update.effective_chat.id
    await update.effective_message.reply_text(message(lang, cardreq_ask_bio, 'cardreq'))
    return WAITING_BIO


async def receive_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)
    bio = update.effective_message.text.strip()
    if text_is_too_long(bio):
        await update.effective_message.reply_text(
            message(lang, 'common.textTooLong', 'common', MAX_TEXT_LENGTH)
        )
        return WAITING_BIO

    db_user = await auth(user.id, user.username)
    chat_id = context.user_data.pop('cardreq_chat_id', update.effective_chat.id)

    request_id = create_card_request(
        user_id=db_user['id'], chat_id=chat_id, bio=bio,
        requester_display_name=user.full_name, requester_username=user.username,
    )
    logger.info("Пользователь %s подал заявку #%d на изменение карточки", user.id, request_id)
    await update.effective_message.reply_text(message(lang, cardreq_submitted, 'cardreq'))

    await notify_admin_new_card_request(context, request_id)  # без bio/user
    return ConversationHandler.END


async def notify_admin_new_card_request(context, request_id):
    from database.queries import get_card_request_by_id
    from handlers.admin_card_requests import _build_card_request_content
    from services.request_broadcast import broadcast_to_admins
    from message.keys import req_claim_button

    req = get_card_request_by_id(request_id)

    async def send_fn(admin_tg_id):
        admin_lang_value = get_user_language(admin_tg_id)
        text = _build_card_request_content(req, admin_lang_value)
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton(message(admin_lang_value, req_claim_button, 'reqclaim'), callback_data=f'cardreqaction:{request_id}:claim'),
        ]])
        return await context.bot.send_message(admin_tg_id, text=text, parse_mode=None, reply_markup=keyboard)

    await broadcast_to_admins(context, 'card', request_id, send_fn)
async def cancel_card_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data.pop('cardreq_chat_id', None)
    await update.effective_message.reply_text(message(lang, cardreq_cancelled, 'cardreq'))
    return ConversationHandler.END


async def my_card_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    db_user = get_user_by_tg_id(user.id)
    requests = get_user_card_requests(db_user['id']) if db_user else []

    if not requests:
        await update.effective_message.reply_text(message(lang, cardreq_my_empty, 'cardreq'))
        return

    status_labels = {
        'pending': cardreq_my_status_pending,
        'approved': cardreq_my_status_approved,
        'rejected': cardreq_my_status_rejected,
    }

    lines = []
    for req in requests:
        status_label = message(lang, status_labels.get(req['status'], cardreq_my_status_pending), 'cardreq')
        preview = req['bio'][:40] + ('…' if len(req['bio']) > 40 else '')
        lines.append(f'«{preview}» — {status_label}')

    await update.effective_message.reply_text('\n'.join(lines))