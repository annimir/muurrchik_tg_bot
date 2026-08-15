import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import get_user_by_tg_id, create_card_request, get_user_card_requests, get_user_language
from config import config
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
    await update.message.reply_text(message(lang, cardreq_ask_bio, 'cardreq'))
    return WAITING_BIO


async def receive_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)
    bio = update.message.text.strip()

    db_user = get_user_by_tg_id(user.id)
    chat_id = context.user_data.pop('cardreq_chat_id', update.effective_chat.id)

    request_id = create_card_request(user_id=db_user['id'], chat_id=chat_id, bio=bio)
    logger.info("Пользователь %s подал заявку #%d на изменение карточки", user.id, request_id)
    await update.message.reply_text(message(lang, cardreq_submitted, 'cardreq'))

    await notify_admin_new_card_request(context, request_id, bio, user)
    return ConversationHandler.END


async def notify_admin_new_card_request(context, request_id, bio, user):
    admin_lang_value = get_user_language(int(config.admin_user_id))

    keyboard = [
        [InlineKeyboardButton(message(admin_lang_value, cardreq_admin_button_approve, 'cardreq'), callback_data=f'cardreqaction:{request_id}:approve')],
        [InlineKeyboardButton(message(admin_lang_value, cardreq_admin_button_edit, 'cardreq'), callback_data=f'cardreqaction:{request_id}:edit')],
        [InlineKeyboardButton(message(admin_lang_value, cardreq_admin_button_reject, 'cardreq'), callback_data=f'cardreqaction:{request_id}:reject')],
    ]
    text = message(
        admin_lang_value, cardreq_admin_notification, 'cardreq',
        request_id, user.full_name, user.username or '—', bio,
    )
    await context.bot.send_message(
        config.admin_user_id, text=text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cancel_card_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data.pop('cardreq_chat_id', None)
    await update.message.reply_text(message(lang, cardreq_cancelled, 'cardreq'))
    return ConversationHandler.END


async def my_card_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подключаю сразу вместе с подачей заявки — не откладываю, как это вышло с /mycharrequests в D2b."""
    user = update.effective_user
    lang = get_user_language(user.id)

    db_user = get_user_by_tg_id(user.id)
    requests = get_user_card_requests(db_user['id']) if db_user else []

    if not requests:
        await update.message.reply_text(message(lang, cardreq_my_empty, 'cardreq'))
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

    await update.message.reply_text('\n'.join(lines))