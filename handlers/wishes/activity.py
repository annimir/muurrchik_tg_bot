import re

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import ensure_user
from database.wish_rewards import record_wish_activity

PRAISE_WORDS = ('молодец', 'лучшая', 'спасибо', 'благодар', 'умница', 'хорошая', 'люблю')
NEGATIVE_PRAISE = re.compile(r'\bне\s+(?:молодец|лучшая|умница|хорошая|люблю)\b')


def is_paimon_praise(text):
    normalized = (text or '').lower().replace('ё', 'е')
    return (
        'паймон' in normalized
        and any(word in normalized for word in PRAISE_WORDS)
        and not NEGATIVE_PRAISE.search(normalized)
    )


async def wish_activity_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.edited_message or not update.effective_user or not update.effective_message:
        return
    message_obj = update.effective_message
    if message_obj.via_bot or message_obj.forward_origin:
        return
    text = (message_obj.text or '').strip()
    if not text:
        return
    tg_user = update.effective_user
    if tg_user.is_bot:
        return
    user = ensure_user(tg_user.id, tg_user.username or tg_user.full_name)
    source_id = f'{update.effective_chat.id}:{message_obj.message_id}'
    record_wish_activity('daily_message', user['id'], 'message', source_id)
    if is_paimon_praise(text):
        record_wish_activity('paimon_praise', user['id'], 'message', source_id)
