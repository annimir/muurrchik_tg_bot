import logging

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from database.queries import get_character_by_name, get_character_subscribers, create_character, get_user_language
from services.tag_storage import tag_storage
from services.mentions import mention_users
from message.loader import message
from message.keys import tag_suggest, tag_created, tag_no_argument

logger = logging.getLogger(__name__)

def create_subscribe_markup(character_name: str, user_id: int | None = None):
    buttons = [[InlineKeyboardButton('Подписаться', callback_data=f'subscribe/{character_name}')]]
    if user_id:
        buttons.append([InlineKeyboardButton('Удалить тэг', callback_data=f'del/{character_name}/{user_id}')])
    return InlineKeyboardMarkup(buttons)


def create_yes_no_markup(matched_name: str, typed_name: str, user_id: int):
    buttons = [
        [InlineKeyboardButton('Да', callback_data=f'tag/{matched_name}/{user_id}')],
        [InlineKeyboardButton('Нет', callback_data=f'new/{typed_name}/{user_id}')],
    ]
    return InlineKeyboardMarkup(buttons)


async def resolve_character_subscribers(update: Update, character_name: str) -> list[str] | None:
    thread_id = update.message.message_thread_id
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    result = tag_storage.find(character_name)

    if result["status"] == "found":
        matched_name = result["tag"]
        character = get_character_by_name(matched_name)
        if not character:
            logger.warning("Рассинхрон кэша тэгов: %s есть в кэше, но нет в БД", matched_name)
            tag_storage.tags.pop(tag_storage.normalize(matched_name), None)
            return await resolve_character_subscribers(update, character_name)

        subs = get_character_subscribers(matched_name)
        return [s['tag'] for s in subs]

    if result["status"] == "suggest":
        logger.info("Пользователю %s предложено уточнение: %s -> %s (%.0f%%)", user_id, character_name, result["tag"], result["score"])
        markup = create_yes_no_markup(result["tag"], character_name, user_id)
        await update.message.reply_text(
            message(lang, tag_suggest, 'tag', result["tag"], f'{result["score"]:.0f}'),
            parse_mode='Markdown', reply_markup=markup, message_thread_id=thread_id,
        )
        return None

    new_name = result["tag"]
    create_character(new_name)
    tag_storage.add_to_cache(new_name)
    logger.info("Пользователь %s создал новый тэг: %s", user_id, new_name)

    markup = create_subscribe_markup(new_name, user_id)
    await update.message.reply_text(
        message(lang, tag_created, 'tag', new_name),
        parse_mode='Markdown', reply_markup=markup, message_thread_id=thread_id,
    )
    return None


async def photo_tag_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_obj = update.message
    thread_id = message_obj.message_thread_id

    if message_obj.via_bot or message_obj.forward_origin:
        return

    if not message_obj.caption or '#' not in message_obj.caption:
        return

    tags = [w[1:] for w in message_obj.caption.split() if w.startswith('#')]

    all_subscribers = []
    for tag in tags:
        subs = await resolve_character_subscribers(update, tag)
        if subs:
            all_subscribers.extend(subs)

    all_subscribers = list(set(all_subscribers))
    if all_subscribers:
        await mention_users(context, update.effective_chat.id, all_subscribers, thread_id)


async def tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    thread_id = update.message.message_thread_id
    lang = get_user_language(update.effective_user.id)

    if not context.args:
        await update.message.reply_text(message(lang, tag_no_argument, 'tag'), message_thread_id=thread_id)
        return

    tags = [w[1:] if w.startswith('#') else w for w in context.args]

    all_subscribers = []
    for tag in tags:
        subs = await resolve_character_subscribers(update, tag)
        if subs:
            all_subscribers.extend(subs)

    all_subscribers = list(set(all_subscribers))
    if all_subscribers:
        await mention_users(context, update.effective_chat.id, all_subscribers, thread_id)