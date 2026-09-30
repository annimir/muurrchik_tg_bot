import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import (
    get_affiliation_by_name_and_parent, add_affiliation, remove_affiliation,
    assign_affiliation_to_character,
    get_user_by_tg_id, create_user, get_user_characters, get_character_by_id, get_user_language,
)
from services.admin import is_admin
from services.affiliation_tree import build_affiliation_tree_flat_with_depth
from message.loader import message
from message.keys import (
    common_private_only, common_not_admin,
    aff_choose_type, aff_button_root, aff_button_child, aff_ask_name, aff_choose_parent,
    aff_name_taken, aff_added, aff_no_affiliations, aff_choose_to_remove, aff_removed,
    aff_list_header, aff_list_empty,
    aff_assign_choose, aff_assign_no_affiliations, aff_assign_forward_prompt, aff_assign_forward_invalid,
    aff_assign_no_characters, aff_assign_choose_character, aff_assign_done,
)

logger = logging.getLogger(__name__)

CHOOSING_TYPE, CHOOSING_PARENT, WAITING_NAME = range(3)
CHOOSING_REMOVE = range(1)[0]
CHOOSING_AFF_FOR_ASSIGN, WAITING_AFF_ASSIGN_FORWARD, CHOOSING_CHARACTER_FOR_AFF = range(3)

INDENT = '　'  # полноширинный пробел — не схлопывается в UI кнопок, в отличие от обычного


async def start_add_affiliation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(user.id):
        await update.message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(message(lang, aff_button_root, 'aff'), callback_data='afftype:root')],
        [InlineKeyboardButton(message(lang, aff_button_child, 'aff'), callback_data='afftype:child')],
    ])
    await update.message.reply_text(message(lang, aff_choose_type, 'aff'), reply_markup=keyboard)
    return CHOOSING_TYPE


async def choose_affiliation_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    kind = query.data.split(':')[1]

    if kind == 'root':
        context.user_data['new_affiliation'] = {'parent_id': None}
        await query.edit_message_text(message(lang, aff_ask_name, 'aff'))
        return WAITING_NAME

    tree = build_affiliation_tree_flat_with_depth()
    if not tree:
        await query.edit_message_text(message(lang, aff_no_affiliations, 'aff'))
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(INDENT * depth + name, callback_data=f'affparent:{aff_id}')]
        for aff_id, name, depth in tree
    ])
    await query.edit_message_text(message(lang, aff_choose_parent, 'aff'), reply_markup=keyboard)
    return CHOOSING_PARENT


async def choose_affiliation_parent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    parent_id = int(query.data.split(':')[1])
    context.user_data['new_affiliation'] = {'parent_id': parent_id}
    await query.edit_message_text(message(lang, aff_ask_name, 'aff'))
    return WAITING_NAME


async def receive_affiliation_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    name = update.message.text.strip()
    data = context.user_data.get('new_affiliation', {'parent_id': None})
    parent_id = data['parent_id']

    if get_affiliation_by_name_and_parent(name, parent_id):
        await update.message.reply_text(message(lang, aff_name_taken, 'aff'))
        return WAITING_NAME

    add_affiliation(name, parent_id)
    logger.info("Админ %s добавил принадлежность '%s' (parent_id=%s)", update.effective_user.id, name, parent_id)
    await update.message.reply_text(message(lang, aff_added, 'aff', name))
    context.user_data.pop('new_affiliation', None)
    return ConversationHandler.END


async def start_remove_affiliation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(user.id):
        await update.message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    tree = build_affiliation_tree_flat_with_depth()
    if not tree:
        await update.message.reply_text(message(lang, aff_no_affiliations, 'aff'))
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(INDENT * depth + name, callback_data=f'affremove:{aff_id}')]
        for aff_id, name, depth in tree
    ])
    await update.message.reply_text(message(lang, aff_choose_to_remove, 'aff'), reply_markup=keyboard)
    return CHOOSING_REMOVE


async def choose_affiliation_to_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    affiliation_id = int(query.data.split(':')[1])
    tree = {aff_id: name for aff_id, name, _ in build_affiliation_tree_flat_with_depth()}
    name = tree.get(affiliation_id, '?')

    remove_affiliation(affiliation_id)
    logger.info("Админ %s удалил принадлежность '%s' (id=%d, вместе с дочерними)", update.effective_user.id, name, affiliation_id)

    await query.edit_message_text(message(lang, aff_removed, 'aff', name))
    return ConversationHandler.END


async def list_affiliations_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.message.reply_text(message(lang, common_not_admin, 'common'))
        return

    tree = build_affiliation_tree_flat_with_depth()
    if not tree:
        await update.message.reply_text(message(lang, aff_list_empty, 'aff'))
        return

    lines = [message(lang, aff_list_header, 'aff')]
    for aff_id, name, depth in tree:
        lines.append(INDENT * depth + f'• {name}')

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


async def start_assign_affiliation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(user.id):
        await update.message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    tree = build_affiliation_tree_flat_with_depth()
    if not tree:
        await update.message.reply_text(message(lang, aff_assign_no_affiliations, 'aff'))
        return ConversationHandler.END

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(INDENT * depth + name, callback_data=f'affassign:{aff_id}')]
        for aff_id, name, depth in tree
    ])
    await update.message.reply_text(message(lang, aff_assign_choose, 'aff'), reply_markup=keyboard)
    return CHOOSING_AFF_FOR_ASSIGN


async def choose_affiliation_for_assign(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    affiliation_id = int(query.data.split(':')[1])
    tree = {aff_id: name for aff_id, name, _ in build_affiliation_tree_flat_with_depth()}
    affiliation_name = tree.get(affiliation_id)
    if not affiliation_name:
        return ConversationHandler.END

    context.user_data['assign_affiliation'] = {'affiliation_id': affiliation_id, 'affiliation_name': affiliation_name}
    await query.edit_message_text(message(lang, aff_assign_forward_prompt, 'aff', affiliation_name))
    return WAITING_AFF_ASSIGN_FORWARD


async def receive_assign_affiliation_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)
    origin = update.message.forward_origin

    if origin is None or origin.type != 'user':
        await update.message.reply_text(message(lang, aff_assign_forward_invalid, 'aff'))
        return WAITING_AFF_ASSIGN_FORWARD

    target_user = origin.sender_user
    db_user = get_user_by_tg_id(target_user.id)
    if not db_user:
        create_user(target_user.id, target_user.username or target_user.full_name)
        db_user = get_user_by_tg_id(target_user.id)

    characters = get_user_characters(db_user['id'])
    if not characters:
        await update.message.reply_text(message(lang, aff_assign_no_characters, 'aff'))
        context.user_data.pop('assign_affiliation', None)
        return ConversationHandler.END

    context.user_data['assign_affiliation']['target_name'] = target_user.full_name

    if len(characters) == 1:
        return await _finalize_affiliation_assignment(update, context, characters[0], lang, via_message=update.message)

    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f'affassigncharacter:{c["id"]}')] for c in characters]
    await update.message.reply_text(
        message(lang, aff_assign_choose_character, 'aff', target_user.full_name),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING_CHARACTER_FOR_AFF


async def choose_character_for_affiliation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = get_user_language(update.effective_user.id)

    if 'assign_affiliation' not in context.user_data:
        return ConversationHandler.END

    character_id = int(query.data.split(':')[1])
    character = get_character_by_id(character_id)
    if not character:
        return ConversationHandler.END

    return await _finalize_affiliation_assignment(update, context, character, lang, via_query=query)


async def _finalize_affiliation_assignment(update, context, character, lang, via_message=None, via_query=None):
    data = context.user_data['assign_affiliation']
    affiliation_id = data['affiliation_id']
    affiliation_name = data['affiliation_name']

    assign_affiliation_to_character(character['id'], affiliation_id)
    logger.info(
        "Админ %s назначил принадлежность '%s' персонажу #%d (%s)",
        update.effective_user.id, affiliation_name, character['id'], character['name'],
    )

    text = message(lang, aff_assign_done, 'aff', character['name'], affiliation_name)

    if via_query:
        await via_query.edit_message_text(text)
    else:
        await via_message.reply_text(text)

    context.user_data.pop('assign_affiliation', None)
    return ConversationHandler.END