import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.queries import get_pending_unclaimed_requests, get_my_claimed_requests, get_user_language
from services.admin import is_admin
from message.loader import message
from message.keys import (
    common_private_only, common_not_admin,
    reqqueue_pending_empty, reqqueue_pending_header, reqqueue_claimed_empty, reqqueue_claimed_header,
    reqqueue_type_character, reqqueue_type_card,
)

logger = logging.getLogger(__name__)

TYPE_LABELS = {'character': reqqueue_type_character, 'card': reqqueue_type_card}
CALLBACK_PREFIX = {'character': 'charreqaction', 'card': 'cardreqaction'}


async def pending_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    rows = get_pending_unclaimed_requests()
    if not rows:
        await update.effective_message.reply_text(message(lang, reqqueue_pending_empty, 'reqqueue'))
        return

    # ДОБАВЛЕНО: раньше это был просто текстовый
    # список без единой кнопки — "перейти и взять в работу" было не на
    # что нажать. Callback_data переиспользует уже существующие
    # ConversationHandler-точки входа (charreqaction:/cardreqaction:) —
    # регистрировать в main.py ничего нового не нужно.
    keyboard = []
    for row in rows:
        type_label = message(lang, TYPE_LABELS[row['request_type']], 'reqqueue')
        button_text = f'#{row["id"]} [{type_label}] {row["label"]}'
        prefix = CALLBACK_PREFIX[row['request_type']]
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f'{prefix}:{row["id"]}:claim')])

    await update.effective_message.reply_text(
        message(lang, reqqueue_pending_header, 'reqqueue'),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def my_claimed_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    rows = get_my_claimed_requests(user.id)
    if not rows:
        await update.effective_message.reply_text(message(lang, reqqueue_claimed_empty, 'reqqueue'))
        return

    lines = [message(lang, reqqueue_claimed_header, 'reqqueue')]
    for row in rows:
        type_label = message(lang, TYPE_LABELS[row['request_type']], 'reqqueue')
        lines.append(f'#{row["id"]} [{type_label}] {row["label"]}')

    await update.effective_message.reply_text('\n'.join(lines), parse_mode=None)