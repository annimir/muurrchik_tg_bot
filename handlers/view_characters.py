import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.queries import get_user_characters, get_user_by_username, get_user_language
from message.loader import message
from message.keys import char_no_characters, char_choose_which, char_user_not_found

logger = logging.getLogger(__name__)


def _character_caption(character: dict, lang: str) -> str:
    parts = [f'*{character["name"]}*']
    if character.get('affiliation'):
        parts.append(f'Принадлежность: {character["affiliation"]}')
    if character.get('position'):
        parts.append(f'Должность: {character["position"]}')
    if character.get('description'):
        parts.append(f'\n{character["description"]}')
    return '\n'.join(parts)


async def _send_character_card(update: Update, context: ContextTypes.DEFAULT_TYPE, character: dict):
    thread_id = update.effective_message.message_thread_id
    lang = get_user_language(update.effective_user.id)
    caption = _character_caption(character, lang)
    photo = character.get('photo_file_id') or character.get('photo_url')

    if photo:
        await context.bot.send_photo(
            update.effective_chat.id, photo=photo, caption=caption,
            parse_mode=None, message_thread_id=thread_id,
        )
    else:
        await context.bot.send_message(
            update.effective_chat.id, caption,
            parse_mode=None, message_thread_id=thread_id,
        )


async def _send_character_menu_or_card(update: Update, context: ContextTypes.DEFAULT_TYPE, characters: list[dict]):
    lang = get_user_language(update.effective_user.id)
    thread_id = update.effective_message.message_thread_id

    if len(characters) == 1:
        await _send_character_card(update, context, characters[0])
        return

    keyboard = [
        [InlineKeyboardButton(c['name'], callback_data=f'showchar:{c["id"]}')]
        for c in characters[:3]  # максимум 3 согласно требованиям
    ]
    await update.effective_message.reply_text(
        message(lang, char_choose_which, 'char'),
        reply_markup=InlineKeyboardMarkup(keyboard),
        message_thread_id=thread_id,
    )


async def my_characters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    from database.queries import get_user_by_tg_id
    db_user = get_user_by_tg_id(user.id)
    characters = get_user_characters(db_user['id']) if db_user else []

    if not characters:
        await update.effective_message.reply_text(message(lang, char_no_characters, 'char'))
        return

    await _send_character_menu_or_card(update, context, characters)


async def character_by_nickname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = get_user_language(update.effective_user.id)

    if not context.args or not context.args[0].startswith('@'):
        await update.effective_message.reply_text('Используйте: /character @nickname')
        return

    username = context.args[0].lstrip('@')
    target_user = get_user_by_username(username)

    if not target_user:
        await update.effective_message.reply_text(message(lang, char_user_not_found, 'char'))
        return

    characters = get_user_characters(target_user['id'])
    if not characters:
        await update.effective_message.reply_text(message(lang, char_no_characters, 'char'))
        return

    await _send_character_menu_or_card(update, context, characters)


async def show_character_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    character_id = int(query.data.split(':')[1])

    from database.queries import get_character_by_id
    character = get_character_by_id(character_id)

    if not character:
        await query.edit_message_text('Персонаж не найден.')
        return

    lang = get_user_language(update.effective_user.id)
    caption = _character_caption(character, lang)
    photo = character.get('photo_file_id') or character.get('photo_url')

    await query.message.delete()
    chat_id = query.message.chat.id
    thread_id = query.message.message_thread_id

    if photo:
        await context.bot.send_photo(chat_id, photo=photo, caption=caption, parse_mode=None, message_thread_id=thread_id)
    else:
        await context.bot.send_message(chat_id, caption, parse_mode=None, message_thread_id=thread_id)