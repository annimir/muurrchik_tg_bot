import logging
from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from database.queries import get_all_birthdays, set_birthday, delete_birthday
from services.admin import is_admin, admin_lang
from message.loader import message
from message.keys import (
    common_private_only, common_not_admin, common_cancel, common_back,
    admin_choose_action, admin_button_add, admin_button_list, admin_button_edit, admin_button_delete,
    admin_forward_prompt, admin_forward_invalid, admin_target_confirmed,
    admin_no_entries, admin_choose_user, admin_entry_not_found,
    admin_entry_card, admin_entry_deleted, admin_date_invalid, admin_saved,
)

logger = logging.getLogger(__name__)

MAIN_MENU, WAITING_FORWARD, WAITING_DATE, MANAGING_ENTRY = range(4)


def _parse_date(raw: str):
    parts = raw.strip().split('.')
    if len(parts) not in (2, 3):
        return None
    try:
        day, month = int(parts[0]), int(parts[1])
        year = int(parts[2]) if len(parts) == 3 else None
        date(year or 2000, month, day)
    except ValueError:
        return None
    return day, month, year


def _back_keyboard(lang):
    return InlineKeyboardMarkup([[InlineKeyboardButton(message(lang, common_back, 'common'), callback_data='nav:back')]])


async def start_admin_birthday(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()

    if update.effective_chat.type != 'private':
        await update.message.reply_text(message(lang, common_private_only, 'common'))
        return ConversationHandler.END
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(message(lang, common_not_admin, 'common'))
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton(message(lang, admin_button_add, 'admin'), callback_data='action:add')],
        [InlineKeyboardButton(message(lang, admin_button_list, 'admin'), callback_data='action:list')],
    ]
    await update.message.reply_text(message(lang, admin_choose_action, 'admin'), reply_markup=InlineKeyboardMarkup(keyboard))
    return MAIN_MENU


async def show_main_menu(query, lang):
    keyboard = [
        [InlineKeyboardButton(message(lang, admin_button_add, 'admin'), callback_data='action:add')],
        [InlineKeyboardButton(message(lang, admin_button_list, 'admin'), callback_data='action:list')],
    ]
    await query.edit_message_text(message(lang, admin_choose_action, 'admin'), reply_markup=InlineKeyboardMarkup(keyboard))
    return MAIN_MENU


async def main_menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = admin_lang()
    action = query.data.split(':')[1]

    if action == 'add':
        await query.edit_message_text(message(lang, admin_forward_prompt, 'admin'), reply_markup=_back_keyboard(lang))
        return WAITING_FORWARD

    if action == 'list':
        rows = get_all_birthdays()

        if not rows:
            await query.edit_message_text(message(lang, admin_no_entries, 'admin'), reply_markup=_back_keyboard(lang))
            return MAIN_MENU

        keyboard = [
            [InlineKeyboardButton(f'{row["tag"]} — {row["day"]:02d}.{row["month"]:02d}', callback_data=f'user:{row["tg_id"]}')]
            for row in rows
        ]
        keyboard.append([InlineKeyboardButton(message(lang, common_back, 'common'), callback_data='nav:back')])

        await query.edit_message_text(message(lang, admin_choose_user, 'admin'), reply_markup=InlineKeyboardMarkup(keyboard))
        return MAIN_MENU


async def receive_forward(update: Update, context: ContextTypes.DEFAULT_TYPE):
    origin = update.message.forward_origin
    lang = admin_lang()

    if origin is None or origin.type != 'user':
        await update.message.reply_text(message(lang, admin_forward_invalid, 'admin'), reply_markup=_back_keyboard(lang))
        return WAITING_FORWARD

    target_user = origin.sender_user
    context.user_data['target_tg_id'] = target_user.id
    context.user_data['target_name'] = target_user.full_name
    context.user_data['target_tag'] = target_user.username or target_user.full_name

    await update.message.reply_text(
        message(lang, admin_target_confirmed, 'admin', target_user.full_name),
        reply_markup=_back_keyboard(lang),
    )
    return WAITING_DATE


async def select_existing_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = admin_lang()

    tg_id = int(query.data.split(':')[1])
    rows = get_all_birthdays()
    row = next((r for r in rows if r['tg_id'] == tg_id), None)

    if not row:
        await query.edit_message_text(message(lang, admin_entry_not_found, 'admin'))
        return await show_main_menu(query, lang)

    context.user_data['target_tg_id'] = row['tg_id']
    context.user_data['target_tag'] = row['tag']
    context.user_data['target_name'] = row['tag']

    year_part = f'.{row["year"]}' if row['year'] else ''
    keyboard = [
        [InlineKeyboardButton(message(lang, admin_button_edit, 'admin'), callback_data='manage:edit')],
        [InlineKeyboardButton(message(lang, admin_button_delete, 'admin'), callback_data='manage:delete')],
        [InlineKeyboardButton(message(lang, common_back, 'common'), callback_data='nav:back')],
    ]
    await query.edit_message_text(
        message(lang, admin_entry_card, 'admin', row["tag"], f'{row["day"]:02d}', f'{row["month"]:02d}', year_part),
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return MANAGING_ENTRY


async def manage_entry_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = admin_lang()
    action = query.data.split(':')[1]

    if action == 'edit':
        await query.edit_message_text(
            message(lang, admin_target_confirmed, 'admin', context.user_data['target_tag']),
            reply_markup=_back_keyboard(lang),
        )
        return WAITING_DATE

    if action == 'delete':
        tg_id = context.user_data['target_tg_id']
        delete_birthday(tg_id)
        logger.info("Админ удалил день рождения пользователя %s", tg_id)

        await query.edit_message_text(message(lang, admin_entry_deleted, 'admin', context.user_data['target_tag']))
        return await show_main_menu(query, lang)


async def go_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    lang = admin_lang()
    return await show_main_menu(query, lang)


async def receive_date(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()
    parsed = _parse_date(update.message.text)

    if not parsed:
        await update.message.reply_text(message(lang, admin_date_invalid, 'admin'), reply_markup=_back_keyboard(lang))
        return WAITING_DATE

    day, month, year = parsed

    set_birthday(
        tg_id=context.user_data['target_tg_id'],
        tag=context.user_data['target_tag'],
        day=day, month=month, year=year,
    )
    logger.info(
        "Админ установил день рождения %02d.%02d для пользователя %s",
        day, month, context.user_data['target_tg_id'],
    )

    await update.message.reply_text(
        message(lang, admin_saved, 'admin', context.user_data['target_name'], f'{day:02d}', f'{month:02d}')
    )
    context.user_data.pop('target_tg_id', None)
    context.user_data.pop('target_tag', None)
    context.user_data.pop('target_name', None)
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = admin_lang()
    context.user_data.clear()
    await update.message.reply_text(message(lang, common_cancel, 'common'))
    return ConversationHandler.END