import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import (
    get_tag_by_name, get_tag_subscriber_count, get_tag_usage_count,
    get_user_by_tg_id, get_user_language,
)
from services.admin import is_admin
from message.loader import message
from message.keys import (
    tagstats_usage, tagstats_not_found, tagstats_header, tagstats_subscribers, tagstats_usage30,
    tagstats_admin_status, tagstats_admin_creator, tagstats_admin_creator_unknown,
    tagstats_admin_last_used, tagstats_admin_last_used_never,
)

logger = logging.getLogger(__name__)


async def tagstats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)
    thread_id = update.effective_message.message_thread_id

    if not context.args:
        await update.effective_message.reply_text(message(lang, tagstats_usage, 'tagstats'), message_thread_id=thread_id)
        return

    name = context.args[0].lower()
    tag = get_tag_by_name(name)

    if not tag:
        await update.effective_message.reply_text(
            message(lang, tagstats_not_found, 'tagstats', name), message_thread_id=thread_id,
        )
        return

    sub_count = get_tag_subscriber_count(tag['id'])
    usage_count = get_tag_usage_count(tag['id'], days=30)

    lines = [
        message(lang, tagstats_header, 'tagstats', tag['name']),
        message(lang, tagstats_subscribers, 'tagstats', sub_count),
        message(lang, tagstats_usage30, 'tagstats', usage_count),
    ]

    admin = is_admin(user.id)
    if admin:
        if tag['created_by']:
            creator = get_user_by_tg_id(tag['created_by'])
            creator_label = creator['tag'] if creator and creator['tag'] else str(tag['created_by'])
        else:
            creator_label = message(lang, tagstats_admin_creator_unknown, 'tagstats')

        last_used_label = (
            tag['last_used_at'].strftime('%Y-%m-%d %H:%M')
            if tag['last_used_at'] else message(lang, tagstats_admin_last_used_never, 'tagstats')
        )

        lines.append(message(lang, tagstats_admin_status, 'tagstats', tag['status']))
        lines.append(message(lang, tagstats_admin_creator, 'tagstats', creator_label))
        lines.append(message(lang, tagstats_admin_last_used, 'tagstats', last_used_label))

    logger.info("Пользователь %s запросил статистику тега '%s' (админ=%s)", user.id, name, admin)
    await update.effective_message.reply_text('\n'.join(lines), parse_mode=None, message_thread_id=thread_id)