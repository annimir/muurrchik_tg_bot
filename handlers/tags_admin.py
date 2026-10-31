import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import get_all_tags, get_tag_by_name, rename_tag, set_tag_status, get_user_language
from services.admin import is_admin
from services.tag_storage import tag_storage
from message.loader import message
from message.keys import (
    common_not_admin, common_private_only,
    char_all_list, char_renamed, char_rename_taken, char_rename_no_argument,
    tagstatus_usage_delete, tagstatus_usage_block, tagstatus_usage_restore,
    tagstatus_not_found, tagstatus_already, tagstatus_deleted, tagstatus_blocked, tagstatus_restored,
)

logger = logging.getLogger(__name__)


async def list_all_tags_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.effective_message.message_thread_id
    lang = get_user_language(user.id)

    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'), message_thread_id=thread_id)
        return

    tags = get_all_tags()
    names = ", ".join(sorted(t['name'] for t in tags if t['status'] == 'ACTIVE'))

    await context.bot.send_message(
        update.effective_chat.id, message(lang, char_all_list, 'char', names),
        parse_mode=None, message_thread_id=thread_id,
    )


async def rename_tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.effective_message.message_thread_id
    lang = get_user_language(user.id)

    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'), message_thread_id=thread_id)
        return

    if len(context.args) < 2:
        await update.effective_message.reply_text(message(lang, char_rename_no_argument, 'char'), message_thread_id=thread_id)
        return

    old_name = context.args[0].lower()
    new_name = context.args[1].lower()

    tag = get_tag_by_name(old_name)
    existing = get_tag_by_name(new_name)

    if not tag:
        await context.bot.send_message(
            update.effective_chat.id, message(lang, 'sub.characterNotFound', 'sub'),
            parse_mode=None, message_thread_id=thread_id,
        )
        return

    if existing:
        await context.bot.send_message(
            update.effective_chat.id, message(lang, char_rename_taken, 'char'),
            parse_mode=None, message_thread_id=thread_id,
        )
        return

    rename_tag(tag['id'], new_name)
    tag_storage.rename(old_name, new_name)
    logger.info("Админ %s переименовал тег %s -> %s", user.id, old_name, new_name)

    await context.bot.send_message(
        update.effective_chat.id, message(lang, char_renamed, 'char', old_name, new_name),
        parse_mode=None, message_thread_id=thread_id,
    )


async def _change_tag_status(update: Update, context: ContextTypes.DEFAULT_TYPE, target_status: str):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    usage_key = {
        'DELETED': tagstatus_usage_delete,
        'BLOCKED': tagstatus_usage_block,
        'ACTIVE': tagstatus_usage_restore,
    }[target_status]

    if not context.args:
        await update.effective_message.reply_text(message(lang, usage_key, 'tagstatus'))
        return

    name = context.args[0].lower()
    tag = get_tag_by_name(name)

    if not tag:
        await update.effective_message.reply_text(message(lang, tagstatus_not_found, 'tagstatus', name))
        return

    if tag['status'] == target_status:
        await update.effective_message.reply_text(message(lang, tagstatus_already, 'tagstatus', name, target_status))
        return

    set_tag_status(tag['id'], target_status)

    if target_status == 'ACTIVE':
        tag_storage.add_to_cache(tag['name'])
        result_key = tagstatus_restored
    else:
        result_key = tagstatus_deleted if target_status == 'DELETED' else tagstatus_blocked

    logger.info("Админ %s перевёл тег '%s' в статус %s", user.id, name, target_status)
    await update.effective_message.reply_text(message(lang, result_key, 'tagstatus', name))


async def delete_tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _change_tag_status(update, context, 'DELETED')


async def block_tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _change_tag_status(update, context, 'BLOCKED')


async def restore_tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _change_tag_status(update, context, 'ACTIVE')