import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_card_request_by_id, update_card_request_status, update_card_request_bio,
    upsert_user_card_bio, get_user_by_id, get_user_language,
)
from services.admin import is_admin, admin_lang
from message.loader import message
from message.keys import (
    cardreq_admin_already_resolved, cardreq_admin_approved_suffix, cardreq_admin_rejected_suffix,
    cardreq_admin_enter_new_bio, cardreq_admin_updated_preview,
    cardreq_admin_button_approve, cardreq_admin_button_edit, cardreq_admin_button_reject,
    cardreq_user_approved, cardreq_user_rejected,
)

logger = logging.getLogger(__name__)

EDITING_BIO = range(1)[0]


async def card_request_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update.effective_user.id):
        return

    lang = admin_lang()
    _, request_id, action = query.data.split(':')
    request_id = int(request_id)
    req = get_card_request_by_id(request_id)

    if not req or req['status'] != 'pending':
        await query.edit_message_text(message(lang, cardreq_admin_already_resolved, 'cardreq'))
        return

    if action == 'approve':
        upsert_user_card_bio(req['user_id'], req['bio'])
        update_card_request_status(request_id, 'approved')
        await notify_card_request_result(context, req, approved=True)
        await query.edit_message_text(query.message.text + message(lang, cardreq_admin_approved_suffix, 'cardreq'))
        logger.info("Админ одобрил заявку на карточку #%d", request_id)

    elif action == 'reject':
        update_card_request_status(request_id, 'rejected')
        await notify_card_request_result(context, req, approved=False)
        await query.edit_message_text(query.message.text + message(lang, cardreq_admin_rejected_suffix, 'cardreq'))
        logger.info("Админ отклонил заявку на карточку #%d", request_id)

    elif action == 'edit':
        context.user_data['editing_cardreq_id'] = request_id
        await query.message.reply_text(message(lang, cardreq_admin_enter_new_bio, 'cardreq'))
        return EDITING_BIO


async def notify_card_request_result(context, req, approved: bool):
    target_user = get_user_by_id(req['user_id'])
    lang = get_user_language(target_user['tg_id']) if target_user else 'RU'
    key = cardreq_user_approved if approved else cardreq_user_rejected
    await context.bot.send_message(chat_id=req['chat_id'], text=message(lang, key, 'cardreq'))


async def receive_card_edit_bio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()
    request_id = context.user_data['editing_cardreq_id']
    new_bio = update.message.text.strip()

    update_card_request_bio(request_id, new_bio)
    logger.info("Админ изменил текст заявки на карточку #%d", request_id)

    req = get_card_request_by_id(request_id)
    keyboard = [
        [InlineKeyboardButton(message(lang, cardreq_admin_button_approve, 'cardreq'), callback_data=f'cardreqaction:{request_id}:approve')],
        [InlineKeyboardButton(message(lang, cardreq_admin_button_edit, 'cardreq'), callback_data=f'cardreqaction:{request_id}:edit')],
        [InlineKeyboardButton(message(lang, cardreq_admin_button_reject, 'cardreq'), callback_data=f'cardreqaction:{request_id}:reject')],
    ]
    await update.message.reply_text(
        message(lang, cardreq_admin_updated_preview, 'cardreq', req['bio']),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    context.user_data.pop('editing_cardreq_id', None)
    return ConversationHandler.END