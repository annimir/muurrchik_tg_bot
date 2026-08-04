import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, filters

from database.queries import (
    get_user_by_tg_id, create_character_request, get_user_requests,
    count_user_characters, get_user_language,
)
from config import config
from message.loader import message
from message.keys import (
    req_ask_name, req_ask_description, req_ask_affiliation, req_ask_position,
    req_ask_photo, req_photo_invalid, req_submitted, req_no_requests,
    req_status_pending, req_status_approved, req_status_rejected,
    req_max_characters_warning, req_cancelled, req_admin_notification,
    req_admin_button_approve, req_admin_button_edit, req_admin_button_reject,
)

logger = logging.getLogger(__name__)

ASK_NAME, ASK_DESCRIPTION, ASK_AFFILIATION, ASK_POSITION, ASK_PHOTO = range(5)

STATUS_KEYS = {
    'pending': req_status_pending,
    'approved': req_status_approved,
    'rejected': req_status_rejected,
}


async def start_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    context.user_data['request'] = {'origin_chat_id': update.effective_chat.id}

    db_user = get_user_by_tg_id(user.id)
    if db_user and count_user_characters(db_user['id']) >= 3:
        await update.message.reply_text(message(lang, req_max_characters_warning, 'req'))

    await update.message.reply_text(message(lang, req_ask_name, 'req'))
    return ASK_NAME


async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data['request']['name'] = update.message.text.strip()
    await update.message.reply_text(message(lang, req_ask_description, 'req'))
    return ASK_DESCRIPTION


async def ask_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data['request']['description'] = update.message.text.strip()
    await update.message.reply_text(message(lang, req_ask_affiliation, 'req'))
    return ASK_AFFILIATION


async def ask_affiliation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data['request']['affiliation'] = update.message.text.strip()
    await update.message.reply_text(message(lang, req_ask_position, 'req'))
    return ASK_POSITION


async def ask_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data['request']['position'] = update.message.text.strip()
    await update.message.reply_text(message(lang, req_ask_photo, 'req'))
    return ASK_PHOTO


async def ask_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)

    if not update.message.photo:
        await update.message.reply_text(message(lang, req_photo_invalid, 'req'))
        return ASK_PHOTO

    photo_file_id = update.message.photo[-1].file_id
    data = context.user_data['request']
    data['photo_file_id'] = photo_file_id

    user = update.effective_user
    db_user = get_user_by_tg_id(user.id)

    request_id = create_character_request(
        user_id=db_user['id'],
        chat_id=data['origin_chat_id'],
        name=data['name'],
        description=data['description'],
        affiliation=data['affiliation'],
        position=data['position'],
        photo_file_id=photo_file_id,
    )

    logger.info("Пользователь %s подал заявку #%d на персонажа '%s'", user.id, request_id, data['name'])
    await update.message.reply_text(message(lang, req_submitted, 'req'))

    await notify_admin_new_request(context, request_id, data, user)

    context.user_data.pop('request', None)
    return ConversationHandler.END


async def notify_admin_new_request(context: ContextTypes.DEFAULT_TYPE, request_id: int, data: dict, user):
    admin_lang = get_user_language(int(config.admin_user_id))

    keyboard = [
        [InlineKeyboardButton(message(admin_lang, req_admin_button_approve, 'req'), callback_data=f'reqaction:{request_id}:approve')],
        [InlineKeyboardButton(message(admin_lang, req_admin_button_edit, 'req'), callback_data=f'reqaction:{request_id}:edit')],
        [InlineKeyboardButton(message(admin_lang, req_admin_button_reject, 'req'), callback_data=f'reqaction:{request_id}:reject')],
    ]
    caption = message(
        admin_lang, req_admin_notification, 'req',
        request_id, user.full_name, user.username or '—',
        data['name'], data['affiliation'], data['position'], data['description'],
    )

    await context.bot.send_photo(
        config.admin_user_id, photo=data['photo_file_id'], caption=caption,
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def cancel_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    context.user_data.pop('request', None)
    await update.message.reply_text(message(lang, req_cancelled, 'req'))
    return ConversationHandler.END


async def my_requests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    db_user = get_user_by_tg_id(user.id)
    requests = get_user_requests(db_user['id']) if db_user else []

    if not requests:
        await update.message.reply_text(message(lang, req_no_requests, 'req'))
        return

    lines = [
        f'{r["name"]} — {message(lang, STATUS_KEYS.get(r["status"], req_status_pending), "req")}'
        for r in requests
    ]
    await update.message.reply_text('\n'.join(lines))