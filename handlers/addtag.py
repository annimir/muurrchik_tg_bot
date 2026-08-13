import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from database.queries import get_tag_by_name, add_tag_alias, find_any_tag_or_alias_owner, get_user_language
from services.tag_storage import tag_storage
from message.loader import message
from message.keys import (
    addtag_usage, addtag_alias_taken, addtag_alias_reserved, addtag_base_not_found, addtag_suggest,
    addtag_confirm_yes, addtag_confirm_no, addtag_cancelled, addtag_no_pending, addtag_success,
)

logger = logging.getLogger(__name__)


def _apply_alias(main_name: str, alias: str):
    tag = get_tag_by_name(main_name)
    add_tag_alias(tag['id'], alias)
    tag_storage.add_alias_to_cache(alias, main_name)


async def _check_alias_collision(update, lang, thread_id, alias) -> bool:
    """
    Возвращает True, если алиас занят (и уже отправлен ответ пользователю).
    ИЗМЕНЕНО (B2): раньше проверяли только tag_storage.is_taken() —
    это кэш, из которого DELETED/BLOCKED теги намеренно убраны, поэтому
    коллизия с ними пропускалась и падала на UNIQUE в БД. Теперь смотрим
    напрямую в БД через find_any_tag_or_alias_owner.
    """
    existing = find_any_tag_or_alias_owner(alias)
    if not existing:
        return False

    if existing['status'] == 'ACTIVE':
        await update.message.reply_text(
            message(lang, addtag_alias_taken, 'addtag', alias, existing['name']),
            parse_mode='Markdown',
        )
    else:
        await update.message.reply_text(
            message(lang, addtag_alias_reserved, 'addtag', alias),
            parse_mode='Markdown',
        )
    return True


async def addtag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = get_user_language(user.id)
    thread_id = update.message.message_thread_id

    if len(context.args) < 2:
        await update.message.reply_text(message(lang, addtag_usage, 'addtag'), message_thread_id=thread_id)
        return

    base_input = context.args[0]
    new_alias = context.args[1].lower()

    if await _check_alias_collision(update, lang, thread_id, new_alias):
        return

    result = tag_storage.find(base_input)

    if result["status"] == "found":
        main_name = result["tag"]
        _apply_alias(main_name, new_alias)
        logger.info("Пользователь %s добавил тег '%s' к '%s'", user.id, new_alias, main_name)
        await update.message.reply_text(
            message(lang, addtag_success, 'addtag', new_alias, main_name),
            parse_mode='Markdown', message_thread_id=thread_id,
        )
        return

    if result["status"] == "suggest":
        context.user_data['pending_alias'] = {'main_name': result["tag"], 'alias': new_alias}
        keyboard = [[
            InlineKeyboardButton(message(lang, addtag_confirm_yes, 'addtag'), callback_data='addtagconfirm:yes'),
            InlineKeyboardButton(message(lang, addtag_confirm_no, 'addtag'), callback_data='addtagconfirm:no'),
        ]]
        await update.message.reply_text(
            message(lang, addtag_suggest, 'addtag', result["tag"], new_alias, f'{result["score"]:.0f}'),
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard), message_thread_id=thread_id,
        )
        return

    logger.warning("Пользователь %s пытался добавить тег к несуществующему '%s'", user.id, base_input)
    await update.message.reply_text(
        message(lang, addtag_base_not_found, 'addtag', base_input), message_thread_id=thread_id,
    )


async def addtag_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user = update.effective_user
    lang = get_user_language(user.id)
    pending = context.user_data.get('pending_alias')

    if not pending:
        await query.edit_message_text(message(lang, addtag_no_pending, 'addtag'))
        return

    choice = query.data.split(':')[1]

    if choice == 'no':
        await query.edit_message_text(message(lang, addtag_cancelled, 'addtag'))
        context.user_data.pop('pending_alias', None)
        return

    main_name = pending['main_name']
    alias = pending['alias']

    # повторная проверка на БД (не только кэш) — гонка между показом
    # кнопок и нажатием могла занять этот алиас за это время
    existing = find_any_tag_or_alias_owner(alias)
    if existing:
        key = addtag_alias_taken if existing['status'] == 'ACTIVE' else addtag_alias_reserved
        args = (alias, existing['name']) if existing['status'] == 'ACTIVE' else (alias,)
        await query.edit_message_text(message(lang, key, 'addtag', *args), parse_mode='Markdown')
        context.user_data.pop('pending_alias', None)
        return

    _apply_alias(main_name, alias)
    logger.info("Пользователь %s подтвердил тег '%s' к '%s'", user.id, alias, main_name)
    await query.edit_message_text(message(lang, addtag_success, 'addtag', alias, main_name), parse_mode='Markdown')
    context.user_data.pop('pending_alias', None)