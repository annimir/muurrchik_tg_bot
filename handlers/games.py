import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.queries import get_user_by_tg_id, create_user, get_user_games, toggle_user_game, get_all_games, get_user_language
from message.loader import message
from message.keys import games_prompt, games_done_button, games_saved_none, games_saved_list

logger = logging.getLogger(__name__)


def _build_keyboard(all_games, selected: set[str], lang: str) -> InlineKeyboardMarkup:
    rows = []
    for game in all_games:
        checkbox = '✅' if game['code'] in selected else '⬜'
        rows.append([InlineKeyboardButton(f'{checkbox} {game["name"]}', callback_data=f'gametoggle:{game["code"]}')])
    rows.append([InlineKeyboardButton(message(lang, games_done_button, 'games'), callback_data='gamesdone')])
    return InlineKeyboardMarkup(rows)


async def mygames_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    db_user = get_user_by_tg_id(user.id)
    if not db_user:
        create_user(user.id, user.username or user.full_name)
        db_user = get_user_by_tg_id(user.id)

    all_games = get_all_games()
    selected = get_user_games(db_user['id'])
    await update.message.reply_text(
        message(lang, games_prompt, 'games'),
        reply_markup=_build_keyboard(all_games, selected, lang),
    )


async def toggle_game_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = get_user_language(user.id)
    db_user = get_user_by_tg_id(user.id)
    if not db_user:
        return

    code = query.data.split(':')[1]
    toggle_user_game(db_user['id'], code)
    logger.info("Пользователь %s переключил игру '%s'", user.id, code)

    all_games = get_all_games()
    selected = get_user_games(db_user['id'])
    await query.edit_message_reply_markup(reply_markup=_build_keyboard(all_games, selected, lang))


async def games_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = get_user_language(user.id)
    db_user = get_user_by_tg_id(user.id)
    selected = get_user_games(db_user['id']) if db_user else set()

    if not selected:
        await query.edit_message_text(message(lang, games_saved_none, 'games'))
        return

    all_games = {g['code']: g['name'] for g in get_all_games()}
    names = ", ".join(all_games[code] for code in selected if code in all_games)
    await query.edit_message_text(message(lang, games_saved_list, 'games', names))