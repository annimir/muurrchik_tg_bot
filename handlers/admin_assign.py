import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, filters

from database.queries import (
    get_all_characters, get_user_by_tg_id, create_user,
    link_user_character, unlink_user_character, get_user_characters,
    count_user_characters, get_user_language,
)
from config import config
from message.loader import message
from message.keys import (
    common_private_only, assign_not_admin, assign_forward_prompt_assign,
    assign_forward_prompt_unassign, assign_forward_invalid, assign_max_reached,
    assign_no_characters_to_unassign, assign_choose_character, assign_choose_to_unassign,
    assign_done, assign_unassign_done,
)

logger = logging.getLogger(__name__)

WAITING_FORWARD, CHOOSING_CHARACTER = range(2)


def _admin_lang():
    return get_user_language(int(config.admin_user_id))


async def start_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END

    if int(update.effective_user.id) != int(config.admin_user_id):
        await update.message.reply_text(message(lang, assign_not_admin, 'assign'))
        return ConversationHandler.END

    context.user_data['assign_mode'] = 'assign'
    await update.message.reply_text(message(lang, assign_forward_prompt_assign, 'assign'))
    return WAITING_FORWARD


async def start_unassign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END

    if int(update.effective_user.id) != int(config.admin_user_id):
        await update.message.reply_text(message(lang, assign_not_admin, 'assign'))
        return ConversationHandler.END

    context.user_data['assign_mode'] = 'unassign'
    await update.message.reply_text(message(lang, assign_forward_prompt_unassign, 'assign'))
    return WAITING_FORWARD


async def receive_target_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = _admin_lang()
    origin = update.message.forward_origin

    if origin is None or origin.type != 'user':
        await update.message.reply_text(message(lang, assign_forward_invalid, 'assign'))
        return WAITING_FORWARD

    target_user = origin.sender_user

    db_user = get_user_by_tg_id(target_user.id)
    if not db_user:
        create_user(target_user.id, target_user.username or target_user.full_name)
        db_user = get_user_by_tg_id(target_user.id)

    context.user_data['target_user_id'] = db_user['id']
    context.user_data['target_tg_id'] = target_user.id
    context.user_data['target_name'] = target_user.full_name

    mode = context.user_data['assign_mode']

    if mode == 'assign':
        if count_user_characters(db_user['id']) >= 3:
            logger.warning(
                "Админ попытался назначить 4-го персонажа пользователю %s — заблокировано",
                target_user.id,
            )
            await update.message.reply_text(
                message(lang, assign_max_reached, 'assign', target_user.full_name)
            )
            return ConversationHandler.END

        all_characters = get_all_characters()
        keyboard = [
            [InlineKeyboardButton(c['name'], callback_data=f'pick:{c["id"]}')]
            for c in all_characters
        ]
        await update.message.reply_text(
            message(lang, assign_choose_character, 'assign'),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CHOOSING_CHARACTER

    else:  # unassign
        current = get_user_characters(db_user['id'])
        if not current:
            await update.message.reply_text(
                message(lang, assign_no_characters_to_unassign, 'assign', target_user.full_name)
            )
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton(c['name'], callback_data=f'pick:{c["id"]}')]
            for c in current
        ]
        await update.message.reply_text(
            message(lang, assign_choose_to_unassign, 'assign'),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return CHOOSING_CHARACTER


async def pick_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = _admin_lang()

    character_id = int(query.data.split(':')[1])
    target_user_id = context.user_data['target_user_id']
    target_tg_id = context.user_data['target_tg_id']
    target_name = context.user_data['target_name']
    mode = context.user_data['assign_mode']

    if mode == 'assign':
        link_user_character(target_user_id, character_id, assigned_by=update.effective_user.id)
        logger.info("Админ назначил персонажа %d пользователю %s", character_id, target_tg_id)
        await query.edit_message_text(message(lang, assign_done, 'assign', target_name))
    else:
        unlink_user_character(target_user_id, character_id)
        logger.info("Админ отвязал персонажа %d от пользователя %s", character_id, target_tg_id)
        await query.edit_message_text(message(lang, assign_unassign_done, 'assign', target_name))

    context.user_data.clear()
    return ConversationHandler.END