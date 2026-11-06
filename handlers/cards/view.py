import html
import logging
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.ext import ContextTypes

from config.config import config
from database.queries import (
    get_user_by_tg_id, create_user, get_user_by_username, get_user_card,
    get_user_games, get_user_characters, get_games_dict, get_character_position,
    get_character_affiliation_names, get_user_language, get_character_by_id,
    get_user_by_id, get_birthday, get_character_tags, get_user_titles,
)
from services.photo import photo_input
from message.loader import message
from message.keys import (
    card_char_desc_none, card_bio_none, card_secondary_label, card_wiki_link_label,
    card_next_page, card_previous_page, card_profile_link_label, card_user_not_found,
    card_usage, card_titles_label, card_birthday_label,
    card_character_birthday_label, card_tags_label, card_games_label,
    card_affiliations_label, card_character_profile_link_label, card_back_to_player,
)

logger = logging.getLogger(__name__)
CARD_PLACEHOLDER = Path(__file__).resolve().parents[2] / 'web' / 'static' / 'card-placeholder.png'


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


def _birthday_text(birthday):
    if not birthday:
        return None
    return f'{birthday["day"]:02}.{birthday["month"]:02}'


def _player_markup(db_user, characters, lang):
    profile_url = f'{config.web_public_base_url}/users/{db_user["id"]}'
    rows = [[InlineKeyboardButton(
        message(lang, card_profile_link_label, 'card'), url=profile_url,
    )]]
    for character in characters:
        rows.append([InlineKeyboardButton(
            _excerpt(character['name'], 60),
            callback_data=f'cardchar:{db_user["id"]}:{character["id"]}',
        )])
    return InlineKeyboardMarkup(rows)


def _character_markup(db_user, character, page, page_count, lang):
    profile_url = f'{config.web_public_base_url}/characters/{character["id"]}'
    actions = [InlineKeyboardButton(
        message(lang, card_character_profile_link_label, 'card'), url=profile_url,
    )]
    if character['wiki_url']:
        actions.append(InlineKeyboardButton(
            message(lang, card_wiki_link_label, 'card'), url=character['wiki_url'],
        ))
    rows = [actions, [InlineKeyboardButton(
        message(lang, card_back_to_player, 'card'),
        callback_data=f'cardplayer:{db_user["id"]}',
    )]]
    if page_count > 1:
        pagination = []
        if page > 0:
            pagination.append(InlineKeyboardButton(
                message(lang, card_previous_page, 'card'),
                callback_data=f'cardchar:{db_user["id"]}:{character["id"]}:{page - 1}',
            ))
        if page + 1 < page_count:
            pagination.append(InlineKeyboardButton(
                message(lang, card_next_page, 'card'),
                callback_data=f'cardchar:{db_user["id"]}:{character["id"]}:{page + 1}',
            ))
        rows.append(pagination)
    return InlineKeyboardMarkup(rows)


def _build_player_card(db_user: dict, display_name: str, lang: str):
    characters = get_user_characters(db_user['id'])
    primary = next((character for character in characters if character['is_primary']), None)
    secondary = [character for character in characters if not character['is_primary']]
    player_line = display_name

    if primary:
        photo = primary['photo_file_id'] or CARD_PLACEHOLDER
        heading = f'<b>{_esc(_excerpt(primary["name"].upper(), 100))}</b>'
        if db_user['chat_position']:
            heading += ' | ' + _esc(_excerpt(db_user['chat_position'], 100))
        blocks = [f'{heading}\n{_esc(player_line)}']
        if secondary:
            names = ', '.join(character['name'] for character in secondary)
            secondary_label = message(lang, card_secondary_label, 'card')
            blocks.append(f'{_esc(secondary_label)} {_esc(_excerpt(names, 160))}')
    else:
        photo = db_user['avatar_file_id']
        blocks = [f'<b>{_esc(player_line)}</b>']

    meta = []
    game_codes = get_user_games(db_user['id'])
    if game_codes:
        games_dict = get_games_dict()
        games_line = ', '.join(games_dict[code] for code in game_codes if code in games_dict)
        if games_line:
            meta.append(_esc(message(
                lang, card_games_label, 'card', _excerpt(games_line, 160),
            )))
    titles = get_user_titles(db_user['id'])
    if titles:
        title_names = ', '.join(title['name'] for title in titles)
        meta.append(_esc(message(
            lang, card_titles_label, 'card', _excerpt(title_names, 160),
        )))
    if primary:
        affiliation_names = get_character_affiliation_names(primary['id'])
        if affiliation_names:
            meta.append(_esc(message(
                lang, card_affiliations_label, 'card', _excerpt(affiliation_names, 160),
            )))
    if meta:
        blocks.append('\n'.join(meta))

    card = get_user_card(db_user['id'])
    bio_text = card['bio'] if card and card['bio'] else message(lang, card_bio_none, 'card')
    blocks.append(_esc(bio_text))

    birthday = _birthday_text(get_birthday(db_user['tg_id']))
    if birthday:
        blocks.append(_esc(message(lang, card_birthday_label, 'card', birthday)))

    if primary:
        description = primary['description'] or message(lang, card_char_desc_none, 'card')
        blocks.append(f'<blockquote>{_esc(_excerpt(description, 240))}</blockquote>')

    return '\n\n'.join(blocks), photo, _player_markup(db_user, characters, lang)


def _description_chunks(text, limit):
    remaining = text.strip()
    while remaining:
        if len(_esc(remaining)) <= limit:
            yield remaining
            return
        split_at = min(len(remaining), limit)
        while split_at > 1 and len(_esc(remaining[:split_at])) > limit:
            split_at -= 1
        word_split = remaining.rfind(' ', 0, split_at)
        if word_split >= split_at // 2:
            split_at = word_split
        yield remaining[:split_at]
        remaining = remaining[split_at:].lstrip()


def _character_tag_text(character_id):
    parts = []
    seen = set()
    for tag in get_character_tags(character_id):
        for name in (tag['name'], *tag['aliases']):
            normalized = name.casefold()
            if normalized not in seen:
                seen.add(normalized)
                parts.append(f'#{name}')
    return ', '.join(parts)


def _build_character_card(db_user, character, lang, page=0):
    heading = f'<b>{_esc(_excerpt(character["name"].upper(), 80))}</b>'
    position = get_character_position(character['id'])
    if position:
        heading += '\n' + _esc(_excerpt(position['name'], 80))
    birthday_block = None
    if character['birth_date']:
        birthday_block = _esc(message(
            lang, card_character_birthday_label, 'card',
            character['birth_date'].strftime('%d.%m'),
        ))
    tag_block = None
    tag_text = _character_tag_text(character['id'])
    if tag_text:
        tag_block = _esc(message(
            lang, card_tags_label, 'card', _excerpt(tag_text, 120),
        ))

    fixed_blocks = [block for block in (heading, birthday_block, tag_block) if block]
    description = character['description'] or message(lang, card_char_desc_none, 'card')
    fixed_length = len('\n\n'.join(fixed_blocks))
    chunks = list(_description_chunks(description, max(80, 960 - fixed_length)))
    page = max(0, min(page, len(chunks) - 1))
    blocks = [heading]
    if birthday_block:
        blocks.append(birthday_block)
    blocks.append(_esc(chunks[page]))
    if tag_block:
        blocks.append(tag_block)

    photo = character['photo_file_id'] or CARD_PLACEHOLDER
    markup = _character_markup(db_user, character, page, len(chunks), lang)
    return '\n\n'.join(blocks), photo, markup


async def _send_card(update: Update, db_user: dict, display_name: str, lang: str):
    thread_id = update.effective_message.message_thread_id
    text, photo, markup = _build_player_card(db_user, display_name, lang)

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


async def _edit_card_message(query, text, photo, markup):
    if query.message.photo:
        media = InputMediaPhoto(
            media=photo_input(photo), caption=text, parse_mode='HTML',
        )
        await query.edit_message_media(media=media, reply_markup=markup)
    else:
        await query.edit_message_text(
            text=text, parse_mode='HTML', reply_markup=markup,
        )


def _display_name(db_user):
    return f'@{db_user["tag"]}' if db_user['tag'] else str(db_user['tg_id'])


async def show_card_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(':')
    action = parts[0]
    lang = get_user_language(query.from_user.id)

    if action in {'cardplayer', 'cardshort'}:
        if action == 'cardplayer':
            db_user = get_user_by_id(int(parts[1]))
        else:
            if len(parts) < 3 or parts[1] != 'char':
                return
            character = get_character_by_id(int(parts[2]))
            if not character:
                return
            db_user = get_user_by_id(character['owner_user_id'])
        if not db_user:
            return
        text, photo, markup = _build_player_card(db_user, _display_name(db_user), lang)
    elif action in {'cardchar', 'carddesc'}:
        if action == 'cardchar':
            db_user = get_user_by_id(int(parts[1]))
            character_id = int(parts[2])
            page = int(parts[3]) if len(parts) > 3 else 0
        else:
            if len(parts) < 3 or parts[1] != 'char':
                return
            character_id = int(parts[2])
            character = get_character_by_id(character_id)
            if not character:
                return
            db_user = get_user_by_id(character['owner_user_id'])
            page = int(parts[3]) if len(parts) > 3 else 0
        character = get_character_by_id(character_id)
        if not db_user or not character or character['owner_user_id'] != db_user['id']:
            return
        text, photo, markup = _build_character_card(db_user, character, lang, page)
    else:
        return

    await _edit_card_message(query, text, photo, markup)


async def card_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    requester = update.effective_user
    lang = get_user_language(requester.id)
    thread_id = update.effective_message.message_thread_id

    if not context.args:
        db_user = get_user_by_tg_id(requester.id)
        if not db_user:
            create_user(requester.id, requester.username or requester.full_name)
            db_user = get_user_by_tg_id(requester.id)

        await _send_card(update, db_user, _display_name(db_user), lang)
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

    await _send_card(update, get_user_by_id(target_user['id']), f'@{username}', lang)
