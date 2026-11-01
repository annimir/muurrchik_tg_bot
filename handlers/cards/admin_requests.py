import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_card_request_by_id, update_card_request_status, update_card_request_bio,
    get_user_by_id, get_user_language, release_request, approve_card_request,
)
from services.admin import is_admin
from services.validation import MAX_TEXT_LENGTH, text_is_too_long
from services.request_broadcast import sync_all_copies, claim_and_sync
from message.loader import message
from message.keys import (
    cardreq_admin_already_resolved, cardreq_admin_approved_suffix, cardreq_admin_rejected_suffix,
    cardreq_admin_enter_new_bio, cardreq_admin_updated_preview, cardreq_admin_notification,
    cardreq_admin_button_approve, cardreq_admin_button_edit, cardreq_admin_button_reject,
    cardreq_user_approved, cardreq_user_rejected, cardreq_summary_label,
    req_claim_button, req_release_button, req_claimed_summary, req_unclaimed_again,
    req_claim_race_lost, req_not_claimed_by_you,
)

logger = logging.getLogger(__name__)

EDITING_BIO = range(1)[0]


def _build_card_request_content(req, lang):
    return message(
        lang, cardreq_admin_notification, 'cardreq',
        req['id'], req['requester_display_name'] or '?', req['requester_username'] or '—', req['bio'],
    )


def _summary_label(req, lang):
    owner_label = req['requester_display_name'] or str(req['user_id'])
    return message(lang, cardreq_summary_label, 'cardreq', req['id'], owner_label)


def _claim_keyboard(request_id, lang):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(message(lang, req_claim_button, 'reqclaim'), callback_data=f'cardreqaction:{request_id}:claim'),
    ]])


def _working_keyboard(request_id, lang):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(message(lang, cardreq_admin_button_approve, 'cardreq'), callback_data=f'cardreqaction:{request_id}:approve')],
        [InlineKeyboardButton(message(lang, cardreq_admin_button_edit, 'cardreq'), callback_data=f'cardreqaction:{request_id}:edit')],
        [InlineKeyboardButton(message(lang, cardreq_admin_button_reject, 'cardreq'), callback_data=f'cardreqaction:{request_id}:reject')],
        [InlineKeyboardButton(message(lang, req_release_button, 'reqclaim'), callback_data=f'cardreqaction:{request_id}:release')],
    ])


async def card_request_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    admin_tg_id = update.effective_user.id
    if not is_admin(admin_tg_id):
        return

    lang = get_user_language(admin_tg_id)
    _, request_id, action = query.data.split(':')
    request_id = int(request_id)
    req = get_card_request_by_id(request_id)

    if not req or req['status'] != 'pending':
        await query.answer(message(lang, cardreq_admin_already_resolved, 'cardreq'), show_alert=True)
        return

    if action == 'claim':
        if req['claimed_by'] is not None:
            await query.answer(message(lang, req_claim_race_lost, 'reqclaim'), show_alert=True)
            return

        claimer_name = update.effective_user.full_name

        def build_claimer_view(target_admin_tg_id):
            target_lang = get_user_language(target_admin_tg_id)
            content = _build_card_request_content(req, target_lang)
            return content, _working_keyboard(request_id, target_lang), False

        def build_other_view(target_admin_tg_id):
            other_lang = get_user_language(target_admin_tg_id)
            label = _summary_label(req, other_lang)
            return message(other_lang, req_claimed_summary, 'reqclaim', label, claimer_name), None, False

        claimed = await claim_and_sync(
            context, 'card', request_id, admin_tg_id, build_claimer_view, build_other_view,
        )
        if not claimed:
            await query.answer(message(lang, req_claim_race_lost, 'reqclaim'), show_alert=True)
            return
        logger.info("Админ %s взял в работу заявку на карточку #%d", admin_tg_id, request_id)
        await query.answer()
        return

    if action == 'release':
        if req['claimed_by'] != admin_tg_id:
            return

        release_request('card', request_id)
        logger.info("Админ %s отложил заявку на карточку #%d", admin_tg_id, request_id)

        label = _summary_label(req, lang)
        await query.edit_message_text(text=message(lang, req_unclaimed_again, 'reqclaim', label), reply_markup=_claim_keyboard(request_id, lang))

        def build(other_admin_tg_id):
            other_lang = get_user_language(other_admin_tg_id)
            other_label = _summary_label(req, other_lang)
            return message(other_lang, req_unclaimed_again, 'reqclaim', other_label), _claim_keyboard(request_id, other_lang)

        await sync_all_copies(context, 'card', request_id, build, exclude_admin_tg_id=admin_tg_id, is_photo=False)
        return

    if req['claimed_by'] != admin_tg_id:
        await query.answer(message(lang, req_not_claimed_by_you, 'reqclaim'), show_alert=True)
        return

    if action == 'approve':
        if not approve_card_request(request_id):
            await query.answer(message(lang, cardreq_admin_already_resolved, 'cardreq'), show_alert=True)
            return
        await notify_card_request_result(context, req, approved=True)
        await query.edit_message_text(text=query.message.text + message(lang, cardreq_admin_approved_suffix, 'cardreq'))
        logger.info("Заявка на карточку #%d одобрена", request_id)

    elif action == 'reject':
        update_card_request_status(request_id, 'rejected')
        await notify_card_request_result(context, req, approved=False)
        await query.edit_message_text(text=query.message.text + message(lang, cardreq_admin_rejected_suffix, 'cardreq'))
        logger.info("Админ %s отклонил заявку на карточку #%d", admin_tg_id, request_id)

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
    lang = get_user_language(update.effective_user.id)
    request_id = context.user_data['editing_cardreq_id']
    new_bio = update.effective_message.text.strip()
    if text_is_too_long(new_bio):
        await update.effective_message.reply_text(
            message(lang, 'common.textTooLong', 'common', MAX_TEXT_LENGTH)
        )
        return EDITING_BIO

    update_card_request_bio(request_id, new_bio)
    logger.info("Админ изменил текст заявки на карточку #%d", request_id)

    req = get_card_request_by_id(request_id)
    keyboard = [
        [InlineKeyboardButton(message(lang, cardreq_admin_button_approve, 'cardreq'), callback_data=f'cardreqaction:{request_id}:approve')],
        [InlineKeyboardButton(message(lang, cardreq_admin_button_edit, 'cardreq'), callback_data=f'cardreqaction:{request_id}:edit')],
        [InlineKeyboardButton(message(lang, cardreq_admin_button_reject, 'cardreq'), callback_data=f'cardreqaction:{request_id}:reject')],
    ]
    await update.effective_message.reply_text(
        message(lang, cardreq_admin_updated_preview, 'cardreq', req['bio']),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    context.user_data.pop('editing_cardreq_id', None)
    return ConversationHandler.END