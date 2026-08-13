import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import (
    get_user_by_tg_id, create_user, get_user_by_username, get_user_flavor_role,
    get_user_games, get_user_characters, get_user_language,
)
from services.games import GAMES
from message.loader import message
from message.keys import (
    card_title, card_role_label, card_role_none, card_games_label, card_games_none,
    card_characters_label, card_characters_none, card_user_not_found, card_usage,
)

logger = logging.getLogger(__name__)


def _format_card(db_user: dict, display_name: str, lang: str) -> str:
    role = get_user_flavor_role(db_user['id'])
    role_text = role['name'] if role else message(lang, card_role_none, 'card')

    game_codes = get_user_games(db_user['id'])
    games_text = ", ".join(GAMES[c] for c in game_codes) if game_codes else message(lang, card_games_none, 'card')

    characters = get_user_characters(db_user['id'])
    chars_text = ", ".join(c['name'] for c in characters) if characters else message(lang, card_characters_none, 'card')

    lines = [
        message(lang, card_title, 'card', display_name),
        f'{message(lang, card_role_label, "card")} {role_text}',
        f'{message(lang, card_games_label, "card")} {games_text}',
        f'{message(lang, card_characters_label, "card")} {chars_text}',
    ]
    return '\n'.join(lines)


async def card_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requester = update.effective_user
    lang = get_user_language(requester.id)
    thread_id = update.message.message_thread_id

    if not context.args:
        db_user = get_user_by_tg_id(requester.id)
        if not db_user:
            create_user(requester.id, requester.username or requester.full_name)
            db_user = get_user_by_tg_id(requester.id)

        text = _format_card(db_user, requester.full_name, lang)
        await update.message.reply_text(text, parse_mode='Markdown', message_thread_id=thread_id)
        return

    if not context.args[0].startswith('@'):
        await update.message.reply_text(message(lang, card_usage, 'card'), message_thread_id=thread_id)
        return

    username = context.args[0].lstrip('@')
    target_user = get_user_by_username(username)

    if not target_user:
        logger.info("Карточка запрошена для неизвестного @%s пользователем %s", username, requester.id)
        await update.message.reply_text(message(lang, card_user_not_found, 'card'), message_thread_id=thread_id)
        return

    text = _format_card(target_user, f'@{username}', lang)
    await update.message.reply_text(text, parse_mode='Markdown', message_thread_id=thread_id)