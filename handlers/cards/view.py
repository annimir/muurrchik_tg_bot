import html
import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config.config import config
from database.queries import (
    get_user_by_tg_id, create_user, get_user_by_username, get_user_card,
    get_user_flavor_role_full, get_user_games, get_user_characters, get_games_dict,
    get_character_position, get_character_affiliation_names, get_user_language,
    get_character_by_id, get_user_by_id,
)
from services.photo import photo_input
from message.loader import message
from message.keys import (
    card_role_none, card_char_desc_none, card_bio_none, card_role_desc_none,
    card_secondary_label, card_wiki_link_label, card_full_description,
    card_short_description, card_next_page, card_previous_page,
    card_profile_link_label, card_user_not_found, card_usage,
)

logger = logging.getLogger(__name__)


def _esc(text: str) -> str:
    return html.escape(str(text), quote=False)


def _excerpt(text, limit):
    normalized = ' '.join(str(text).split())
    if len(normalized) <= limit:
        return normalized
    if limit <= 1:
        return '…' if limit else ''
    shortened = normalized[:limit - 1].rsplit(' ', 1)[0]
    return f'{shortened}…'


def _card_markup(db_user, role, description_target, lang, wiki_url=None):
    rows = []
    if description_target:
        rows.append([InlineKeyboardButton(
            message(lang, card_full_description, 'card'),
            callback_data=f'carddesc:{description_target}',
        )])
    wiki_url = wiki_url or (role['wiki_url'] if role else None)
    if wiki_url:
        rows.append([InlineKeyboardButton(
            message(lang, card_wiki_link_label, 'card'), url=wiki_url,
        )])
    profile_url = f'{config.web_public_base_url}/users/{db_user["id"]}'
    rows.append([InlineKeyboardButton(
        message(lang, card_profile_link_label, 'card'), url=profile_url,
    )])
    return InlineKeyboardMarkup(rows)


def _description_markup(db_user, role, target, page, page_count, lang, wiki_url=None):
    rows = [[InlineKeyboardButton(
        message(lang, card_short_description, 'card'),
        callback_data=f'cardshort:{target}',
    )]]
    if page_count > 1:
        pagination = []
        if page > 0:
            pagination.append(InlineKeyboardButton(
                message(lang, card_previous_page, 'card'),
                callback_data=f'carddesc:{target}:{page - 1}',
            ))
        if page + 1 < page_count:
            pagination.append(InlineKeyboardButton(
                message(lang, card_next_page, 'card'),
                callback_data=f'carddesc:{target}:{page + 1}',
            ))
        rows.append(pagination)
    wiki_url = wiki_url or (role['wiki_url'] if role else None)
    if wiki_url:
        rows.append([InlineKeyboardButton(
            message(lang, card_wiki_link_label, 'card'), url=wiki_url,
        )])
    profile_url = f'{config.web_public_base_url}/users/{db_user["id"]}'
    rows.append([InlineKeyboardButton(
        message(lang, card_profile_link_label, 'card'), url=profile_url,
    )])
    return InlineKeyboardMarkup(rows)


def _build_card(db_user: dict, display_name: str, lang: str):
    characters = get_user_characters(db_user['id'])
    primary = next((character for character in characters if character['is_primary']), None)
    secondary = [character for character in characters if not character['is_primary']]
    role = get_user_flavor_role_full(db_user['id'])

    if primary:
        title = primary['name'].upper()
        photo = primary['photo_file_id']
    else:
        title = role['name'] if role else message(lang, card_role_none, 'card')
        photo = role['photo_file_id'] if role else None

    lines = [f'<b>{_esc(_excerpt(title, 100))}</b>\n{_esc(display_name)}']
    if secondary:
        names = ', '.join(character['name'] for character in secondary)
        secondary_label = message(lang, card_secondary_label, 'card')
        lines.append(f'{_esc(secondary_label)} {_esc(_excerpt(names, 160))}')

    game_codes = get_user_games(db_user['id'])
    if game_codes:
        games_dict = get_games_dict()
        games_line = ', '.join(games_dict[code] for code in game_codes if code in games_dict)
        if games_line:
            lines.append(_esc(_excerpt(games_line, 160)))

    if primary:
        position = get_character_position(primary['id'])
        if position:
            lines.append(_esc(_excerpt(position['name'], 100)))
        affiliation_names = get_character_affiliation_names(primary['id'])
        if affiliation_names:
            lines.append(_esc(_excerpt(affiliation_names, 160)))

    card = get_user_card(db_user['id'])
    bio_text = card['bio'] if card and card['bio'] else message(lang, card_bio_none, 'card')
    lines.append(_esc(_excerpt(bio_text, 240)))

    description_target = None
    if primary and primary['description']:
        description = primary['description']
        description_target = f'char:{primary["id"]}'
    elif role and role['description']:
        description = role['description']
        description_target = f'role:{db_user["id"]}'
    elif primary:
        description = message(lang, card_char_desc_none, 'card')
    else:
        description = message(lang, card_role_desc_none, 'card')

    base_text = '\n\n'.join(lines)
    remaining = 1024 - len(base_text) - len('<blockquote></blockquote>') - 2
    if remaining >= 32:
        lines.append(f'<blockquote>{_esc(_excerpt(description, min(240, remaining)))}</blockquote>')

    text = '\n\n'.join(lines)
    wiki_url = primary['wiki_url'] if primary and primary['wiki_url'] else None
    markup = _card_markup(db_user, role, description_target, lang, wiki_url)
    return text, photo, markup


async def _send_card(update: Update, db_user: dict, display_name: str, lang: str):
    thread_id = update.effective_message.message_thread_id
    text, photo, markup = _build_card(db_user, display_name, lang)

    if photo and len(text) <= 1024:
        await update.effective_message.reply_photo(
            photo=photo_input(photo), caption=text, parse_mode='HTML',
            reply_markup=markup, message_thread_id=thread_id,
        )
        return
    if photo:
        await update.effective_message.reply_photo(
            photo=photo_input(photo), message_thread_id=thread_id,
        )
    await update.effective_message.reply_text(
        text, parse_mode='HTML', reply_markup=markup, message_thread_id=thread_id,
    )


def _description_chunks(text, limit=700):
    remaining = text.strip()
    while remaining:
        if len(remaining) <= limit:
            yield remaining
            return
        split_at = remaining.rfind(' ', 0, limit)
        if split_at < limit // 2:
            split_at = limit
        yield remaining[:split_at]
        remaining = remaining[split_at:].lstrip()


async def _edit_card_message(query, text, markup):
    if query.message.photo:
        await query.edit_message_caption(
            caption=text, parse_mode='HTML', reply_markup=markup,
        )
    else:
        await query.edit_message_text(
            text=text, parse_mode='HTML', reply_markup=markup,
        )


async def show_card_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(':')
    action, target, identifier = parts[0], parts[1], int(parts[2])
    page = int(parts[3]) if len(parts) > 3 else 0

    if target == 'char':
        character = get_character_by_id(identifier)
        if not character:
            return
        db_user = get_user_by_id(character['owner_user_id'])
        role = get_user_flavor_role_full(db_user['id'])
        title = character['name']
        description = character['description']
        wiki_url = character['wiki_url']
    else:
        db_user = get_user_by_id(identifier)
        role = get_user_flavor_role_full(identifier)
        title = role['name'] if role else ''
        description = role['description'] if role else None
        wiki_url = None

    lang = get_user_language(query.from_user.id)
    if action == 'cardshort':
        text, _, markup = _build_card(db_user, db_user['tag'] or title, lang)
        await _edit_card_message(query, text, markup)
        return
    if not description:
        return

    chunks = list(_description_chunks(description))
    page = max(0, min(page, len(chunks) - 1))
    text = f'<b>{_esc(title)}</b>\n\n<blockquote>{_esc(chunks[page])}</blockquote>'
    markup = _description_markup(
        db_user, role, f'{target}:{identifier}', page, len(chunks), lang, wiki_url,
    )
    await _edit_card_message(query, text, markup)


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
