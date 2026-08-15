import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import (
    get_user_by_tg_id, create_user, get_user_by_username, get_user_card,
    get_user_flavor_role, get_user_games, get_user_characters, get_user_language,
)
from services.games import GAMES
from message.loader import message
from message.keys import (
    card_title, card_bio_label, card_bio_none, card_role_label, card_role_none,
    card_games_label, card_games_none, card_characters_label, card_characters_none,
    card_user_not_found, card_usage,
)

logger = logging.getLogger(__name__)


def _build_card(db_user: dict, display_name: str, lang: str):
    card = get_user_card(db_user['id'])
    bio_text = card['bio'] if card and card['bio'] else message(lang, card_bio_none, 'card')

    role = get_user_flavor_role(db_user['id'])
    role_text = role['name'] if role else message(lang, card_role_none, 'card')

    game_codes = get_user_games(db_user['id'])
    games_text = ", ".join(GAMES[c] for c in game_codes) if game_codes else message(lang, card_games_none, 'card')

    # get_user_characters уже сортирует is_primary DESC, created_at (D1) —
    # основной персонаж гарантированно первый в списке
    characters = get_user_characters(db_user['id'])
    primary = next((c for c in characters if c['is_primary']), None)

    if characters:
        chars_text = ", ".join(
            (f'⭐{c["name"]}' if c['is_primary'] else c['name']) for c in characters
        )
    else:
        chars_text = message(lang, card_characters_none, 'card')

    lines = [
        message(lang, card_title, 'card', display_name),
        f'{message(lang, card_bio_label, "card")} {bio_text}',
        f'{message(lang, card_role_label, "card")} {role_text}',
        f'{message(lang, card_games_label, "card")} {games_text}',
        f'{message(lang, card_characters_label, "card")} {chars_text}',
    ]
    text = '\n'.join(lines)
    photo = primary['photo_file_id'] if primary else None
    return text, photo


async def _send_card(update: Update, db_user: dict, display_name: str, lang: str):
    thread_id = update.message.message_thread_id
    text, photo = _build_card(db_user, display_name, lang)

    if photo:
        await update.message.reply_photo(photo=photo, caption=text, message_thread_id=thread_id)
    else:
        await update.message.reply_text(text, message_thread_id=thread_id)


async def card_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requester = update.effective_user
    lang = get_user_language(requester.id)
    thread_id = update.message.message_thread_id

    if not context.args:
        db_user = get_user_by_tg_id(requester.id)
        if not db_user:
            create_user(requester.id, requester.username or requester.full_name)
            db_user = get_user_by_tg_id(requester.id)

        await _send_card(update, db_user, requester.full_name, lang)
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

    await _send_card(update, target_user, f'@{username}', lang)