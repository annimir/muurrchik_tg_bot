import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler, filters

from database.queries import (
    get_all_characters, get_user_by_tg_id, create_user,
    link_user_character, unlink_user_character, get_user_characters,
)
from config import config

logger = logging.getLogger(__name__)

CHOOSING_ACTION, WAITING_FORWARD, CHOOSING_CHARACTER = range(3)


async def start_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return ConversationHandler.END
    if int(update.effective_user.id) != int(config.admin_user_id):
        await update.message.reply_text('Эта команда только для админа.')
        return ConversationHandler.END

    context.user_data['assign_mode'] = 'assign'
    await update.message.reply_text('Перешлите сообщение пользователя, которому назначаем персонажа.')
    return WAITING_FORWARD


async def start_unassign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != 'private':
        return ConversationHandler.END
    if int(update.effective_user.id) != int(config.admin_user_id):
        await update.message.reply_text('Эта команда только для админа.')
        return ConversationHandler.END

    context.user_data['assign_mode'] = 'unassign'
    await update.message.reply_text('Перешлите сообщение пользователя, у которого отменяем привязку.')
    return WAITING_FORWARD


async def receive_target_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    origin = update.message.forward_origin
    if origin is None or origin.type != 'user':
        await update.message.reply_text('Это не похоже на пересланное сообщение от пользователя.')
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
        current = get_user_characters(db_user['id'])
        if len(current) >= 3:
            await update.message.reply_text(
                f'У {target_user.full_name} уже максимум персонажей (3). Сначала отвяжите одного через /unassign_character.'
            )
            return ConversationHandler.END

        all_characters = get_all_characters()
        keyboard = [
            [InlineKeyboardButton(c['name'], callback_data=f'pick:{c["id"]}')]
            for c in all_characters
        ]
        await update.message.reply_text('Какого персонажа назначить?', reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSING_CHARACTER

    else:  # unassign
        current = get_user_characters(db_user['id'])
        if not current:
            await update.message.reply_text(f'У {target_user.full_name} нет привязанных персонажей.')
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton(c['name'], callback_data=f'pick:{c["id"]}')]
            for c in current
        ]
        await update.message.reply_text('Кого отвязать?', reply_markup=InlineKeyboardMarkup(keyboard))
        return CHOOSING_CHARACTER


async def pick_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    character_id = int(query.data.split(':')[1])
    target_user_id = context.user_data['target_user_id']
    mode = context.user_data['assign_mode']

    if mode == 'assign':
        link_user_character(target_user_id, character_id, assigned_by=update.effective_user.id)
        logger.info("Админ назначил персонажа %d пользователю %s", character_id, context.user_data['target_tg_id'])
        await query.edit_message_text(f'Готово! Персонаж назначен {context.user_data["target_name"]}.')
    else:
        unlink_user_character(target_user_id, character_id)
        logger.info("Админ отвязал персонажа %d от пользователя %s", character_id, context.user_data['target_tg_id'])
        await query.edit_message_text(f'Готово! Привязка отменена у {context.user_data["target_name"]}.')

    context.user_data.clear()
    return ConversationHandler.END