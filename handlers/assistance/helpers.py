import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import TelegramError
from telegram.ext import ContextTypes

from database.assistance import (
    disable_helper, get_helper_profile, list_assistance_games, list_game_modes,
    list_helper_modes, set_helper_dm_available, set_helper_mode, set_helper_paused,
)
from database.queries import ensure_user, get_user_by_tg_id, get_user_language
from message.keys import (
    helper_button_back, helper_button_close, helper_button_disable, helper_button_no,
    helper_button_yes, helper_closed, helper_disable, helper_disable_confirm,
    helper_disabled, helper_dm_required, helper_enabled_dm, helper_menu,
    helper_menu_empty, helper_menu_paused, helper_no_games, helper_no_modes,
    helper_only_owner, helper_pause, helper_resume, helper_started,
)
from message.loader import message

logger = logging.getLogger(__name__)


def _data(tg_id, action, value=''):
    suffix = f':{value}' if value != '' else ''
    return f'helper:{tg_id}:{action}{suffix}'


def _main_menu(db_user, lang):
    profile = get_helper_profile(db_user['id'])
    modes = list_helper_modes(db_user['id'], active_only=True)
    if not modes:
        text = message(lang, helper_menu_empty, 'helper')
    else:
        mode_names = '\n'.join(f'• {row["game_name"]}: {row["mode_name"]}' for row in modes)
        text = message(lang, helper_menu, 'helper', mode_names)
        if profile and profile['is_paused']:
            text += f'\n\n{message(lang, helper_menu_paused, "helper")}'
    games = list_assistance_games()
    if not games:
        text += f'\n\n{message(lang, helper_no_games, "helper")}'
    buttons = [
        [InlineKeyboardButton(game['name'], callback_data=_data(db_user['tg_id'], 'game', game['code']))]
        for game in games
    ]
    if profile and modes:
        pause_key = helper_resume if profile['is_paused'] else helper_pause
        buttons.append([InlineKeyboardButton(
            message(lang, pause_key, 'helper'), callback_data=_data(db_user['tg_id'], 'pause'),
        )])
        buttons.append([InlineKeyboardButton(
            message(lang, helper_button_disable, 'helper'),
            callback_data=_data(db_user['tg_id'], 'disable'),
        )])
    buttons.append([InlineKeyboardButton(
        message(lang, helper_button_close, 'helper'), callback_data=_data(db_user['tg_id'], 'close'),
    )])
    return text, InlineKeyboardMarkup(buttons)


def _mode_menu(db_user, game_code, lang):
    games = {game['code']: game for game in list_assistance_games()}
    game = games.get(game_code)
    modes = list_game_modes(game_code)
    if not game or not modes:
        return message(lang, helper_no_modes, 'helper'), None
    selected = {row['mode_id']: row['is_active'] for row in list_helper_modes(db_user['id'])}
    buttons = [
        [InlineKeyboardButton(
            f'{"✅" if selected.get(mode["id"]) else "⬜"} {mode["name"]}',
            callback_data=_data(db_user['tg_id'], 'toggle', mode['id']),
        )]
        for mode in modes
    ]
    buttons.append([InlineKeyboardButton(
        message(lang, helper_button_back, 'helper'), callback_data=_data(db_user['tg_id'], 'back'),
    )])
    return game['name'], InlineKeyboardMarkup(buttons)


async def helper_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    lang = get_user_language(tg_user.id)
    db_user = ensure_user(tg_user.id, tg_user.username or tg_user.full_name)
    if update.effective_chat.type == 'private':
        set_helper_dm_available(db_user['id'], True)
    text, markup = _main_menu(db_user, lang)
    await update.effective_message.reply_text(text, reply_markup=markup)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_user = update.effective_user
    db_user = ensure_user(tg_user.id, tg_user.username or tg_user.full_name)
    if get_helper_profile(db_user['id']):
        set_helper_dm_available(db_user['id'], True)
        await update.effective_message.reply_text(
            message(get_user_language(tg_user.id), helper_started, 'helper'),
        )
        return
    await helper_command(update, context)


async def helper_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    lang = get_user_language(query.from_user.id)
    parts = query.data.split(':')
    if len(parts) < 3:
        await query.answer()
        return
    owner_id, action = parts[1], parts[2]
    value = parts[3] if len(parts) > 3 else ''
    if owner_id != str(query.from_user.id):
        await query.answer(message(lang, helper_only_owner, 'helper'), show_alert=True)
        return
    db_user = get_user_by_tg_id(query.from_user.id)
    if not db_user:
        await query.answer()
        return

    if action == 'close':
        await query.edit_message_text(message(lang, helper_closed, 'helper'))
    elif action == 'back':
        text, markup = _main_menu(db_user, lang)
        await query.edit_message_text(text, reply_markup=markup)
    elif action == 'game':
        text, markup = _mode_menu(db_user, value, lang)
        await query.edit_message_text(text, reply_markup=markup)
    elif action == 'toggle':
        mode_id = int(value)
        current = {
            row['mode_id']: row['is_active'] for row in list_helper_modes(db_user['id'])
        }.get(mode_id, False)
        enabled = set_helper_mode(db_user['id'], mode_id, not current)
        if enabled is None:
            await query.answer(message(lang, helper_no_modes, 'helper'), show_alert=True)
            return
        if enabled and query.message.chat.type == 'private':
            set_helper_dm_available(db_user['id'], True)
        elif enabled:
            try:
                await context.bot.send_message(
                    query.from_user.id, message(lang, helper_enabled_dm, 'helper'),
                )
                set_helper_dm_available(db_user['id'], True)
            except TelegramError:
                set_helper_dm_available(db_user['id'], False)
                logger.info('Помогатор %s должен запустить ЛС бота', query.from_user.id)
                await context.bot.send_message(
                    query.message.chat.id, message(lang, helper_dm_required, 'helper'),
                )
        game = get_mode_game(mode_id)
        text, markup = _mode_menu(db_user, game, lang)
        await query.edit_message_text(text, reply_markup=markup)
    elif action == 'pause':
        profile = get_helper_profile(db_user['id'])
        if profile:
            set_helper_paused(db_user['id'], not profile['is_paused'])
        text, markup = _main_menu(db_user, lang)
        await query.edit_message_text(text, reply_markup=markup)
    elif action == 'disable':
        await query.edit_message_text(
            f'{message(lang, helper_disable, "helper")}\n{message(lang, helper_disable_confirm, "helper")}',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    message(lang, helper_button_yes, 'helper'),
                    callback_data=_data(db_user['tg_id'], 'disable_yes'),
                ),
                InlineKeyboardButton(
                    message(lang, helper_button_no, 'helper'),
                    callback_data=_data(db_user['tg_id'], 'back'),
                ),
            ]]),
        )
    elif action == 'disable_yes':
        disable_helper(db_user['id'])
        await query.edit_message_text(message(lang, helper_disabled, 'helper'))
    await query.answer()


def get_mode_game(mode_id):
    from database.assistance import get_game_mode

    mode = get_game_mode(mode_id)
    return mode['game_code']
