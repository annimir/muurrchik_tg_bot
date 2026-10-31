import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import get_user_language, add_admin, remove_admin, get_all_admin_ids, count_admins
from services.admin import is_admin
from message.loader import message
from message.keys import (
    common_private_only, common_not_admin,
    adminmgmt_add_forward_prompt, adminmgmt_add_forward_invalid, adminmgmt_already_admin, adminmgmt_added,
    adminmgmt_remove_forward_prompt, adminmgmt_remove_forward_invalid, adminmgmt_not_admin_target,
    adminmgmt_removed, adminmgmt_cannot_remove_last,
    adminmgmt_list_header, adminmgmt_list_empty,
)

logger = logging.getLogger(__name__)

WAITING_ADD_FORWARD = range(1)[0]
WAITING_REMOVE_FORWARD = range(1)[0]


async def start_add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    await update.effective_message.reply_text(message(lang, adminmgmt_add_forward_prompt, 'adminmgmt'))
    return WAITING_ADD_FORWARD


async def receive_add_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    origin = update.effective_message.forward_origin

    if origin is None or origin.type != 'user':
        await update.effective_message.reply_text(message(lang, adminmgmt_add_forward_invalid, 'adminmgmt'))
        return WAITING_ADD_FORWARD

    target_user = origin.sender_user

    if target_user.id in get_all_admin_ids():
        await update.effective_message.reply_text(message(lang, adminmgmt_already_admin, 'adminmgmt', target_user.full_name))
        return ConversationHandler.END

    add_admin(target_user.id)
    logger.info("Админ %s добавил нового админа %s (%s)", update.effective_user.id, target_user.id, target_user.full_name)
    await update.effective_message.reply_text(message(lang, adminmgmt_added, 'adminmgmt', target_user.full_name))
    return ConversationHandler.END


async def start_remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    await update.effective_message.reply_text(message(lang, adminmgmt_remove_forward_prompt, 'adminmgmt'))
    return WAITING_REMOVE_FORWARD


async def receive_remove_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    origin = update.effective_message.forward_origin

    if origin is None or origin.type != 'user':
        await update.effective_message.reply_text(message(lang, adminmgmt_remove_forward_invalid, 'adminmgmt'))
        return WAITING_REMOVE_FORWARD

    target_user = origin.sender_user

    if target_user.id not in get_all_admin_ids():
        await update.effective_message.reply_text(message(lang, adminmgmt_not_admin_target, 'adminmgmt', target_user.full_name))
        return ConversationHandler.END

    if count_admins() <= 1:
        logger.warning(
            "Админ %s пытался удалить последнего админа (%s) — заблокировано",
            update.effective_user.id, target_user.id,
        )
        await update.effective_message.reply_text(message(lang, adminmgmt_cannot_remove_last, 'adminmgmt'))
        return ConversationHandler.END

    remove_admin(target_user.id)
    logger.info("Админ %s удалил админа %s (%s)", update.effective_user.id, target_user.id, target_user.full_name)
    await update.effective_message.reply_text(message(lang, adminmgmt_removed, 'adminmgmt', target_user.full_name))
    return ConversationHandler.END


async def list_admins_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    admin_ids = get_all_admin_ids()
    if not admin_ids:
        await update.effective_message.reply_text(message(lang, adminmgmt_list_empty, 'adminmgmt'))
        return

    lines = "\n".join(f'• {tg_id}' for tg_id in sorted(admin_ids))
    await update.effective_message.reply_text(f'{message(lang, adminmgmt_list_header, "adminmgmt")}\n{lines}')