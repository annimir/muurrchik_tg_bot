import logging

from telegram import Update
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


async def pending_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.message.reply_text(message(lang, common_not_admin, 'common'))
        return

    rows = get_pending_unclaimed_requests()
    if not rows:
        await update.message.reply_text(message(lang, reqqueue_pending_empty, 'reqqueue'))
        return

    lines = [message(lang, reqqueue_pending_header, 'reqqueue')]
    for row in rows:
        type_label = message(lang, TYPE_LABELS[row['request_type']], 'reqqueue')
        lines.append(f'#{row["id"]} [{type_label}] {row["label"]}')

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


async def my_claimed_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.message.reply_text(message(lang, common_not_admin, 'common'))
        return

    rows = get_my_claimed_requests(user.id)
    if not rows:
        await update.message.reply_text(message(lang, reqqueue_claimed_empty, 'reqqueue'))
        return

    lines = [message(lang, reqqueue_claimed_header, 'reqqueue')]
    for row in rows:
        type_label = message(lang, TYPE_LABELS[row['request_type']], 'reqqueue')
        lines.append(f'#{row["id"]} [{type_label}] {row["label"]}')

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')