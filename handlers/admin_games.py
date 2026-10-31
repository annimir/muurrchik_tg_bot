import logging

from telegram import Update
from telegram.ext import ContextTypes

from database.queries import (
    get_all_games, get_game_by_name, game_code_exists, add_game, remove_game,
    count_users_with_game, get_user_language,
)
from services.admin import is_admin
from services.games import slugify_game_name
from message.loader import message
from message.keys import (
    common_private_only, common_not_admin,
    admingames_usage_add, admingames_already_exists, admingames_added,
    admingames_usage_remove, admingames_not_found, admingames_removed,
    admingames_list_header, admingames_list_empty,
)

logger = logging.getLogger(__name__)


async def add_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    if not context.args:
        await update.effective_message.reply_text(message(lang, admingames_usage_add, 'admingames'))
        return

    name = ' '.join(context.args).strip()

    if get_game_by_name(name):
        await update.effective_message.reply_text(message(lang, admingames_already_exists, 'admingames', name))
        return

    base_slug = slugify_game_name(name)
    code = base_slug
    suffix = 2
    while game_code_exists(code):
        code = f'{base_slug}_{suffix}'
        suffix += 1

    add_game(code, name)
    logger.info("Админ %s добавил игру '%s' (code=%s)", user.id, name, code)
    await update.effective_message.reply_text(message(lang, admingames_added, 'admingames', name))


async def remove_game_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    if not context.args:
        await update.effective_message.reply_text(message(lang, admingames_usage_remove, 'admingames'))
        return

    name = ' '.join(context.args).strip()
    game = get_game_by_name(name)

    if not game:
        await update.effective_message.reply_text(message(lang, admingames_not_found, 'admingames', name))
        return

    affected_count = count_users_with_game(game['code'])
    remove_game(game['code'])
    logger.info("Админ %s удалил игру '%s', затронуто пользователей: %d", user.id, name, affected_count)

    await update.effective_message.reply_text(message(lang, admingames_removed, 'admingames', name, affected_count))


async def list_games_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)

    if update.effective_chat.type != 'private':
        await update.effective_message.reply_text(message(lang, common_private_only, 'common'))
        return
    if not is_admin(user.id):
        await update.effective_message.reply_text(message(lang, common_not_admin, 'common'))
        return

    games = get_all_games()
    if not games:
        await update.effective_message.reply_text(message(lang, admingames_list_empty, 'admingames'))
        return

    names = "\n".join(f'• {g["name"]}' for g in games)
    await update.effective_message.reply_text(f'{message(lang, admingames_list_header, "admingames")}\n{names}', parse_mode=None)