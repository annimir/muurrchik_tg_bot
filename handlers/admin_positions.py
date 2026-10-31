import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_all_positions, get_all_positions_with_holders, get_position_by_name,
    add_position, remove_position, get_position_holder_character,
    assign_position_to_character, revoke_position_by_id,
    get_user_by_tg_id, create_user, get_user_characters, get_character_by_id, get_user_language,
)
from services.admin import is_admin
from message.loader import message
from message.keys import (
    common_private_only, common_not_admin,
    adminpos_usage_add, adminpos_already_exists, adminpos_added,
    adminpos_usage_remove, adminpos_not_found, adminpos_removed,
    adminpos_list_header, adminpos_list_empty, adminpos_list_vacant, adminpos_list_holder,
    adminpos_assign_choose_position, adminpos_assign_no_positions,
    adminpos_assign_forward_prompt, adminpos_assign_forward_invalid,
    adminpos_assign_no_characters, adminpos_assign_choose_character,
    adminpos_assign_done, adminpos_assign_done_with_revoke,
    adminpos_revoke_no_occupied, adminpos_revoke_choose, adminpos_revoke_done,
)

logger = logging.getLogger(__name__)

CHOOSING_POSITION, WAITING_ASSIGN_FORWARD, CHOOSING_CHARACTER_FOR_POSITION = range(3)
CHOOSING_REVOKE_POSITION = range(1)[0]


async def add_position_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    if not context.args:
        await update.effective_message.reply_text(message(lang, adminpos_usage_add, 'adminpos'))
        return

    name = ' '.join(context.args).strip()
    position_id = add_position(name)

    if position_id is None:
        await update.effective_message.reply_text(message(lang, adminpos_already_exists, 'adminpos', name))
        return

    logger.info("Админ %s добавил должность '%s' (id=%d)", user.id, name, position_id)
    await update.effective_message.reply_text(message(lang, adminpos_added, 'adminpos', name))


async def remove_position_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    if not context.args:
        await update.effective_message.reply_text(message(lang, adminpos_usage_remove, 'adminpos'))
        return

    name = ' '.join(context.args).strip()
    position = get_position_by_name(name)

    if not position:
        await update.effective_message.reply_text(message(lang, adminpos_not_found, 'adminpos', name))
        return

    remove_position(position['id'])  # ON DELETE SET NULL сам освобождает держателя, если он был
    logger.info("Админ %s удалил должность '%s'", user.id, name)
    await update.effective_message.reply_text(message(lang, adminpos_removed, 'adminpos', name))


async def list_positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    rows = get_all_positions_with_holders()
    if not rows:
        await update.effective_message.reply_text(message(lang, adminpos_list_empty, 'adminpos'))
        return

    lines = [message(lang, adminpos_list_header, 'adminpos')]
    for row in rows:
        if row['character_name']:
            status = message(lang, adminpos_list_holder, 'adminpos', f'{row["character_name"]} (@{row["owner_tag"]})')
        else:
            status = message(lang, adminpos_list_vacant, 'adminpos')
        lines.append(f'• {row["name"]} — {status}')

    await update.effective_message.reply_text('\n'.join(lines), parse_mode=None)


async def start_assign_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    positions = get_all_positions()
    if not positions:
        await update.effective_message.reply_text(message(lang, adminpos_assign_no_positions, 'adminpos'))
        return ConversationHandler.END

    keyboard = [[InlineKeyboardButton(p['name'], callback_data=f'posassign:{p["id"]}')] for p in positions]
    await update.effective_message.reply_text(message(lang, adminpos_assign_choose_position, 'adminpos'), reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_POSITION


async def choose_position_for_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    position_id = int(query.data.split(':')[1])
    positions = {p['id']: p['name'] for p in get_all_positions()}
    position_name = positions.get(position_id)
    if not position_name:
        return ConversationHandler.END

    context.user_data['assign_position'] = {'position_id': position_id, 'position_name': position_name}
    await query.edit_message_text(message(lang, adminpos_assign_forward_prompt, 'adminpos', position_name))
    return WAITING_ASSIGN_FORWARD


async def receive_assign_position_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    origin = update.effective_message.forward_origin

    if origin is None or origin.type != 'user':
        await update.effective_message.reply_text(message(lang, adminpos_assign_forward_invalid, 'adminpos'))
        return WAITING_ASSIGN_FORWARD

    target_user = origin.sender_user
    db_user = get_user_by_tg_id(target_user.id)
    if not db_user:
        create_user(target_user.id, target_user.username or target_user.full_name)
        db_user = get_user_by_tg_id(target_user.id)

    characters = get_user_characters(db_user['id'])
    if not characters:
        await update.effective_message.reply_text(message(lang, adminpos_assign_no_characters, 'adminpos'))
        context.user_data.pop('assign_position', None)
        return ConversationHandler.END

    context.user_data['assign_position']['target_name'] = target_user.full_name
    context.user_data['assign_position']['target_tg_id'] = target_user.id

    if len(characters) == 1:
        return await _finalize_position_assignment(update, context, characters[0], lang, via_message=update.effective_message)

    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f'posassigncharacter:{c["id"]}')] for c in characters]
    await update.effective_message.reply_text(
        message(lang, adminpos_assign_choose_character, 'adminpos', target_user.full_name),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING_CHARACTER_FOR_POSITION


async def choose_character_for_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    if 'assign_position' not in context.user_data:
        return ConversationHandler.END

    character_id = int(query.data.split(':')[1])
    character = get_character_by_id(character_id)
    data = context.user_data['assign_position']
    target_user = get_user_by_tg_id(data['target_tg_id'])
    if (
        not character or not target_user
        or character['owner_user_id'] != target_user['id']
    ):
        return ConversationHandler.END

    return await _finalize_position_assignment(update, context, character, lang, via_query=query)


async def _finalize_position_assignment(update, context, character, lang, via_message=None, via_query=None):
    data = context.user_data['assign_position']
    position_id = data['position_id']
    position_name = data['position_name']

    previous_holder = get_position_holder_character(position_id)
    assign_position_to_character(character['id'], position_id)

    admin_tg_id = update.effective_user.id
    logger.info(
        "Админ %s назначил должность '%s' персонажу #%d (%s)",
        admin_tg_id, position_name, character['id'], character['name'],
    )

    if previous_holder and previous_holder['id'] != character['id']:
        text = message(
            lang, adminpos_assign_done_with_revoke, 'adminpos',
            position_name, character['name'], previous_holder['name'],
        )
    else:
        text = message(lang, adminpos_assign_done, 'adminpos', position_name, character['name'])

    if via_query:
        await via_query.edit_message_text(text)
    else:
        await via_message.reply_text(text)

    context.user_data.pop('assign_position', None)
    return ConversationHandler.END


async def start_revoke_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    rows = get_all_positions_with_holders()
    occupied = [r for r in rows if r['character_name']]

    if not occupied:
        await update.effective_message.reply_text(message(lang, adminpos_revoke_no_occupied, 'adminpos'))
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(f'{r["name"]} — {r["character_name"]}', callback_data=f'posrevoke:{r["id"]}')]
        for r in occupied
    ]
    await update.effective_message.reply_text(message(lang, adminpos_revoke_choose, 'adminpos'), reply_markup=InlineKeyboardMarkup(keyboard))
    return CHOOSING_REVOKE_POSITION


async def choose_revoke_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    position_id = int(query.data.split(':')[1])
    holder = get_position_holder_character(position_id)

    if not holder:
        return ConversationHandler.END

    positions = {p['id']: p['name'] for p in get_all_positions()}
    position_name = positions.get(position_id, '?')

    revoke_position_by_id(position_id)
    logger.info("Админ %s снял должность '%s' с персонажа #%d", update.effective_user.id, position_name, holder['id'])

    await query.edit_message_text(message(lang, adminpos_revoke_done, 'adminpos', position_name, holder['name']))
    return ConversationHandler.END