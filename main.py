import logging

from telegram.ext import (
    Application, CommandHandler, MessageHandler, InlineQueryHandler,
    CallbackQueryHandler, ChatMemberHandler, ConversationHandler, filters,
)

from config.logging_config import setup_logging
from config import config

from database.queries import get_all_characters, get_all_aliases
from services.tag_storage import tag_storage

from handlers.welcome import welcome_new_member
from handlers.language import language_command
from handlers.birthday import set_birthday_command, my_birthday_command, delete_birthday_command
from handlers.birthday_job import check_birthdays
from handlers.chat_tracking import track_bot_membership
from handlers.subscriptions import my_subscriptions, subscribe, unsubscribe
from handlers.unsuball import unsuball_command, unsuball_confirm_callback
from handlers.characters_admin import list_all_characters, delete_character_command, rename_character_command
from handlers.user_profile import update_me
from handlers.tagging import photo_tag_handler, tag_command
from handlers.addtag import addtag_command, addtag_confirm_callback
from handlers.inline_search import inline_search
from handlers.callbacks import callback_router
from handlers.birthday_admin_dm import (
    start_admin_birthday, choose_chat, main_menu_router, receive_forward,
    select_existing_user, manage_entry_router, go_back, receive_date, cancel,
    CHOOSING_CHAT, MAIN_MENU, WAITING_FORWARD, WAITING_DATE, MANAGING_ENTRY,
)
from handlers.view_characters import my_characters, character_by_nickname, show_character_callback
from handlers.character_requests import (
    start_request, ask_name, ask_description, ask_affiliation, ask_position, ask_photo,
    cancel_request, my_requests, ASK_NAME, ASK_DESCRIPTION, ASK_AFFILIATION, ASK_POSITION, ASK_PHOTO,
)
from handlers.admin_requests import (
    request_action_callback, choose_edit_field, receive_edit_value, EDITING_FIELD, EDITING_VALUE,
)
from handlers.admin_assign import (
    start_assign, start_unassign, receive_target_forward, pick_character, WAITING_FORWARD, CHOOSING_CHARACTER,
)
from handlers.admin_edit_character import (
    start_edit_character, choose_character_to_edit, choose_field, receive_new_value,
    CHOOSING_FIELD as EDIT_CHOOSING_FIELD, WAITING_VALUE as EDIT_WAITING_VALUE,
)

from datetime import time
from zoneinfo import ZoneInfo

from services.character_sync import sync_characters_from_sheet
import asyncio

setup_logging()
logger = logging.getLogger(__name__)

application = Application.builder().token(config.bot_token).build()


async def error_handler(update, context):
    logger.error("Необработанное исключение: %s", update, exc_info=context.error)

async def sync_characters_job(context):
    await asyncio.to_thread(sync_characters_from_sheet)

application.add_error_handler(error_handler)

# служебные
application.add_handler(ChatMemberHandler(track_bot_membership, ChatMemberHandler.MY_CHAT_MEMBER))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))

# язык
application.add_handler(CommandHandler('language', language_command))

# дни рождения — группа
application.add_handler(CommandHandler('setbirthday', set_birthday_command))
application.add_handler(CommandHandler('mybirthday', my_birthday_command))
application.add_handler(CommandHandler('deletebirthday', delete_birthday_command))

# дни рождения — админ в личке
admin_birthday_conv = ConversationHandler(
    entry_points=[CommandHandler('admin_birthdays', start_admin_birthday, filters=filters.ChatType.PRIVATE)],
    states={
        CHOOSING_CHAT: [CallbackQueryHandler(choose_chat, pattern=r'^chat:')],
        MAIN_MENU: [
            CallbackQueryHandler(main_menu_router, pattern=r'^action:'),
            CallbackQueryHandler(select_existing_user, pattern=r'^user:'),
        ],
        WAITING_FORWARD: [
            CallbackQueryHandler(go_back, pattern=r'^nav:back'),
            MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_forward),
        ],
        WAITING_DATE: [
            CallbackQueryHandler(go_back, pattern=r'^nav:back'),
            MessageHandler(filters.TEXT & ~filters.COMMAND, receive_date),
        ],
        MANAGING_ENTRY: [
            CallbackQueryHandler(manage_entry_router, pattern=r'^manage:'),
            CallbackQueryHandler(go_back, pattern=r'^nav:back'),
        ],
    },
    fallbacks=[CommandHandler('cancel', cancel)],
)
application.add_handler(admin_birthday_conv)

MOSCOW_TZ = ZoneInfo('Europe/Moscow')
application.job_queue.run_daily(check_birthdays, time=time(hour=9, minute=0, tzinfo=MOSCOW_TZ))
application.job_queue.run_daily(
    sync_characters_job,
    time=time(hour=4, minute=0, tzinfo=MOSCOW_TZ),  # ночью, вне пиковой активности
)

all_characters = get_all_characters()
tag_storage.load_from([c['name'] for c in all_characters])

alias_rows = get_all_aliases()
tag_storage.load_aliases([(row['alias'], row['name']) for row in alias_rows])

# подписки
application.add_handler(CommandHandler('mysub', my_subscriptions))
application.add_handler(CommandHandler('sub', subscribe))
application.add_handler(CommandHandler('unsub', unsubscribe))
application.add_handler(CommandHandler('unsuball', unsuball_command))
application.add_handler(CallbackQueryHandler(unsuball_confirm_callback, pattern=r'^unsuballconfirm:'))

# персонажи (админ)
application.add_handler(CommandHandler('all', list_all_characters))
application.add_handler(CommandHandler('del', delete_character_command))
application.add_handler(CommandHandler('rename', rename_character_command))

# профиль
application.add_handler(CommandHandler('updateme', update_me))

# тэги
application.add_handler(CommandHandler('tag', tag_command))
application.add_handler(MessageHandler(filters.PHOTO & filters.CAPTION, photo_tag_handler))
application.add_handler(CommandHandler('addtag', addtag_command))
application.add_handler(CallbackQueryHandler(addtag_confirm_callback, pattern=r'^addtagconfirm:'))

# inline
application.add_handler(InlineQueryHandler(inline_search))

# callback-и подписок/тэгов (после ConversationHandler, паттерн исключает конфликт с nav/manage/chat/action)
application.add_handler(CallbackQueryHandler(callback_router, pattern=r'^(subscribe|tag|new|del)/'))

# просмотр персонажей — группа
application.add_handler(CommandHandler('mycharacters', my_characters))
application.add_handler(CommandHandler('character', character_by_nickname))
application.add_handler(CallbackQueryHandler(show_character_callback, pattern=r'^showchar:'))

# заявки
request_conv = ConversationHandler(
    entry_points=[CommandHandler('newcharacter', start_request)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
        ASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_description)],
        ASK_AFFILIATION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_affiliation)],
        ASK_POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_position)],
        ASK_PHOTO: [MessageHandler(filters.PHOTO, ask_photo)],
    },
    fallbacks=[CommandHandler('cancel', cancel_request)],
)
application.add_handler(request_conv)
application.add_handler(CommandHandler('myrequests', my_requests))

# обработка заявки админом
request_review_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(request_action_callback, pattern=r'^reqaction:')],
    states={
        EDITING_FIELD: [CallbackQueryHandler(choose_edit_field, pattern=r'^reqedit:')],
        EDITING_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edit_value)],
    },
    fallbacks=[],
    per_message=False,
)
application.add_handler(request_review_conv)

# назначение/отмена персонажа
assign_conv = ConversationHandler(
    entry_points=[
        CommandHandler('assign_character', start_assign, filters=filters.ChatType.PRIVATE),
        CommandHandler('unassign_character', start_unassign, filters=filters.ChatType.PRIVATE),
    ],
    states={
        WAITING_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_target_forward)],
        CHOOSING_CHARACTER: [CallbackQueryHandler(pick_character, pattern=r'^pick:')],
    },
    fallbacks=[],
)
application.add_handler(assign_conv)

# редактирование карточки персонажа
edit_character_conv = ConversationHandler(
    entry_points=[CommandHandler('edit_character', start_edit_character, filters=filters.ChatType.PRIVATE)],
    states={
        EDIT_CHOOSING_FIELD: [CallbackQueryHandler(choose_field, pattern=r'^field:')],
        EDIT_WAITING_VALUE: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, receive_new_value)],
    },
    fallbacks=[],
)
application.add_handler(edit_character_conv)

logger.info("Бот запущен")
application.run_polling()