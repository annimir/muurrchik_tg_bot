import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.auth import auth
from services.tag_storage import tag_storage
from database.queries import (
    get_all_characters, delete_character, get_character_by_name,
    update_character_name, get_user_language,
)
from message.loader import message
from message.keys import (
    common_not_admin, char_all_list, char_deleted, char_renamed,
    char_rename_taken, char_rename_no_argument, char_delete_no_argument,
)
from config import config

logger = logging.getLogger(__name__)


def is_admin(user_id: int) -> bool:
    return int(user_id) == int(config.admin_user_id)


async def list_all_characters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.message.message_thread_id

    await auth(user.id, user.username)
    lang = get_user_language(user.id)

    if not is_admin(user.id):
        logger.warning("Пользователь %s без прав попытался вызвать /all", user.id)
        await update.message.reply_text(message(lang, common_not_admin, 'common'), message_thread_id=thread_id)
        return

    all_characters = get_all_characters()
    names = ", ".join(sorted(c['name'] for c in all_characters))

    await context.bot.send_message(
        update.effective_chat.id, message(lang, char_all_list, 'char', names),
        parse_mode='Markdown', message_thread_id=thread_id,
    )


async def delete_character_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.message.message_thread_id
    lang = get_user_language(user.id)

    if not is_admin(user.id):
        logger.warning("Пользователь %s без прав попытался вызвать /del", user.id)
        await update.message.reply_text(message(lang, common_not_admin, 'common'), message_thread_id=thread_id)
        return

    if not context.args:
        await update.message.reply_text(message(lang, char_delete_no_argument, 'char'), message_thread_id=thread_id)
        return

    character_name = context.args[0].lower()
    character = get_character_by_name(character_name)

    if not character:
        await context.bot.send_message(
            update.effective_chat.id, message(lang, 'sub.characterNotFound', 'sub'),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    delete_character(character_name)
    tag_storage.tags.pop(tag_storage.normalize(character_name), None)
    logger.info("Админ %s удалил персонажа %s", user.id, character_name)

    await context.bot.send_message(
        update.effective_chat.id, message(lang, char_deleted, 'char', character_name),
        parse_mode='Markdown', message_thread_id=thread_id,
    )


async def rename_character_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    thread_id = update.message.message_thread_id
    lang = get_user_language(user.id)

    if not is_admin(user.id):
        logger.warning("Пользователь %s без прав попытался вызвать /rename", user.id)
        await update.message.reply_text(message(lang, common_not_admin, 'common'), message_thread_id=thread_id)
        return

    if len(context.args) < 2:
        await update.message.reply_text(message(lang, char_rename_no_argument, 'char'), message_thread_id=thread_id)
        return

    old_name = context.args[0].lower()
    new_name = context.args[1].lower()

    character = get_character_by_name(old_name)
    existing = get_character_by_name(new_name)

    if not character:
        await context.bot.send_message(
            update.effective_chat.id, message(lang, 'sub.characterNotFound', 'sub'),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    if existing:
        await context.bot.send_message(
            update.effective_chat.id, message(lang, char_rename_taken, 'char'),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    update_character_name(character['id'], new_name)
    tag_storage.tags.pop(tag_storage.normalize(old_name), None)
    tag_storage.add_to_cache(new_name)
    logger.info("Админ %s переименовал персонажа %s -> %s", user.id, old_name, new_name)

    await context.bot.send_message(
        update.effective_chat.id, message(lang, char_renamed, 'char', old_name, new_name),
        parse_mode='Markdown', message_thread_id=thread_id,
    )