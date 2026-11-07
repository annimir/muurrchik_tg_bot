import logging

from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.assistance import expire_help_requests
from database.queries import get_user_language
from handlers.assistance.requests import _edit_group_request
from message.keys import assist_expired
from message.loader import message

logger = logging.getLogger(__name__)


async def expire_assistance_requests(context: ContextTypes.DEFAULT_TYPE):
    for request in expire_help_requests():
        lang = get_user_language(request['requester_tg_id'])
        text = message(lang, assist_expired, 'assist', request['id'])
        try:
            await _edit_group_request(context, request, text)
        except TelegramError:
            logger.warning('Не удалось уведомить чат об истечении заявки %s', request['id'])
        if request['helper_tg_id']:
            try:
                await context.bot.send_message(request['helper_tg_id'], text)
            except TelegramError:
                logger.warning('Не удалось уведомить помогатора об истечении заявки %s', request['id'])
