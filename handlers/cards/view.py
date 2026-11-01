import html
import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import (
    get_user_by_tg_id, create_user, get_user_by_username, get_user_card,
    get_user_flavor_role_full, get_user_games, get_user_characters, get_games_dict,
    get_character_position, get_character_affiliation_path, get_user_language,
)
from message.loader import message
from message.keys import (
    card_role_none, card_char_desc_none, card_bio_none, card_role_desc_none,
    card_secondary_label, card_wiki_link_label,
    card_user_not_found, card_usage,
)

logger = logging.getLogger(__name__)


def _esc(text: str) -> str:
    """
    HTML-экранирование пользовательского текста перед вставкой в сообщение
    с parse_mode='HTML'. Без этого < > & в чьём-то био или описании
    персонажа сломают разметку всего сообщения (в лучшем случае) или
    вызовут ошибку API (в худшем).
    """
    return html.escape(text, quote=False)


def _build_card(db_user: dict, display_name: str, lang: str):
    characters = get_user_characters(db_user['id'])  # уже отсортированы: is_primary DESC
    primary = next((c for c in characters if c['is_primary']), None)
    secondary = [c for c in characters if not c['is_primary']]
    has_character = primary is not None

    if has_character:
        title = primary['name'].upper()
        photo = primary['photo_file_id']
    else:
        role = get_user_flavor_role_full(db_user['id'])
        title = role['name'] if role else message(lang, card_role_none, 'card')
        photo = role['photo_file_id'] if role else None

    lines = [f'<b>{_esc(title)}</b>\n{_esc(display_name)}']

    if secondary:
        names = ", ".join(c['name'] for c in secondary)
        lines.append(f'{_esc(message(lang, card_secondary_label, "card"))} {_esc(names)}')

    game_codes = get_user_games(db_user['id'])
    if game_codes:
        games_dict = get_games_dict()
        games_line = ", ".join(games_dict[c] for c in game_codes if c in games_dict)
        if games_line:
            lines.append(_esc(games_line))

    if has_character:
        position = get_character_position(primary['id'])
        if position:
            lines.append(_esc(position['name']))

        affiliation_path = get_character_affiliation_path(primary['id'])
        if affiliation_path:
            lines.append(_esc(affiliation_path))

    card = get_user_card(db_user['id'])
    bio_text = card['bio'] if card and card['bio'] else message(lang, card_bio_none, 'card')
    lines.append(_esc(bio_text))

    if has_character:
        desc = primary['description'] if primary['description'] else message(lang, card_char_desc_none, 'card')
        quote_text = _esc(desc)
    else:
        role = get_user_flavor_role_full(db_user['id'])
        if role and role['description']:
            quote_text = _esc(role['description'])
            if role['wiki_url']:
                wiki_label = _esc(message(lang, card_wiki_link_label, 'card'))
                wiki_url = html.escape(role['wiki_url'], quote=True)
                quote_text += f'\n<a href="{wiki_url}">{wiki_label}</a>'
        else:
            quote_text = _esc(message(lang, card_role_desc_none, 'card'))

    lines.append(f'<blockquote>{quote_text}</blockquote>')

    text = '\n\n'.join(lines)
    return text, photo


async def _send_card(update: Update, db_user: dict, display_name: str, lang: str):
    thread_id = update.effective_message.message_thread_id
    text, photo = _build_card(db_user, display_name, lang)

    if photo and len(text) <= 1024:
        await update.effective_message.reply_photo(photo=photo, caption=text, parse_mode='HTML', message_thread_id=thread_id)
        return
    if photo:
        await update.effective_message.reply_photo(photo=photo, message_thread_id=thread_id)
    await update.effective_message.reply_text(text, parse_mode='HTML', message_thread_id=thread_id)


async def card_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requester = update.effective_user
    lang = get_user_language(requester.id)
    thread_id = update.effective_message.message_thread_id

    if not context.args:
        db_user = get_user_by_tg_id(requester.id)
        if not db_user:
            create_user(requester.id, requester.username or requester.full_name)
            db_user = get_user_by_tg_id(requester.id)

        await _send_card(update, db_user, requester.full_name, lang)
        return

    if not context.args[0].startswith('@'):
        await update.effective_message.reply_text(message(lang, card_usage, 'card'), message_thread_id=thread_id)
        return

    username = context.args[0].lstrip('@')
    target_user = get_user_by_username(username)

    if not target_user:
        logger.info("Карточка запрошена для неизвестного @%s пользователем %s", username, requester.id)
        await update.effective_message.reply_text(message(lang, card_user_not_found, 'card'), message_thread_id=thread_id)
        return

    await _send_card(update, target_user, f'@{username}', lang)