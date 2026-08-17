import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram.ext import (
    Application, CommandHandler, MessageHandler, InlineQueryHandler,
    CallbackQueryHandler, ChatMemberHandler, ConversationHandler, filters,
)

from config.logging_config import setup_logging
from config import config

from handlers.welcome import welcome_new_member
from handlers.language import language_command
from handlers.birthday import set_birthday_command, my_birthday_command, delete_birthday_command
from handlers.birthday_job import check_birthdays
from handlers.chat_tracking import track_bot_membership
from handlers.membership_tracking import track_member_left
from handlers.retention_job import send_retention_warnings, run_retention_cleanup
from handlers.subscriptions import my_subscriptions, subscribe, unsubscribe
from handlers.unsuball import unsuball_command, unsuball_confirm_callback
from handlers.tags_admin import (
    list_all_tags_command, rename_tag_command,
    delete_tag_command, block_tag_command, restore_tag_command,
)
from handlers.user_profile import update_me
from handlers.tagging import media_tag_handler, tag_command
from handlers.inline_search import inline_search
from handlers.callbacks import callback_router
from handlers.addtag import addtag_command, addtag_confirm_callback
from handlers.admin_roles import (
    add_role_command, remove_role_command, list_roles_command,
    start_reroll_role, receive_reroll_forward, WAITING_REROLL_FORWARD,
    backfill_cards_command,
)
from handlers.tag_stats import tagstats_command
from handlers.games import mygames_command, toggle_game_callback, games_done_callback
from handlers.birthday_admin_dm import (
    start_admin_birthday, main_menu_router, receive_forward,
    select_existing_user, manage_entry_router, go_back, receive_date, cancel,
    MAIN_MENU, WAITING_FORWARD, WAITING_DATE, MANAGING_ENTRY,
)
from handlers.character_requests import (
    start_character_request, ask_name, ask_birthdate, ask_description, ask_photo,
    cancel_character_request, ASK_NAME, ASK_BIRTHDATE, ASK_DESCRIPTION, ASK_PHOTO, my_character_requests,
)
from handlers.character_edit import (
    start_character_edit, pick_character, choose_field, receive_edit_value, cancel_character_edit,
    CHOOSE_CHARACTER, CHOOSE_FIELD, WAITING_VALUE,
)
from handlers.admin_character_requests import (
    character_request_action_callback, choose_charreq_edit_field, receive_charreq_edit_value,
    EDITING_FIELD, EDITING_VALUE,
)
from handlers.character_primary import setprimary_command, setprimary_callback
from handlers.admin_character_primary import (
    start_admin_setprimary, receive_admin_setprimary_forward, admin_setprimary_callback,
    WAITING_FORWARD, CHOOSING_CHARACTER,
)
from handlers.character_birthday_job import check_character_birthdays
from handlers.card_request import start_card_request, receive_bio, cancel_card_request, my_card_requests, WAITING_BIO
from handlers.admin_card_requests import card_request_action_callback, receive_card_edit_bio, EDITING_BIO
from handlers.card import card_command
from database.queries import bootstrap_admin_if_empty
from handlers.admin_management import (
    start_add_admin, receive_add_forward, start_remove_admin, receive_remove_forward,
    list_admins_command, WAITING_ADD_FORWARD, WAITING_REMOVE_FORWARD,
)
from handlers.admin_request_queue import pending_requests_command, my_claimed_requests_command


from database.queries import get_active_tags, get_all_tag_aliases
from services.tag_storage import tag_storage

setup_logging()
logger = logging.getLogger(__name__)
bootstrap_admin_if_empty(config.admin_user_id)

application = Application.builder().token(config.bot_token).build()

async def error_handler(update, context):
    logger.error("Необработанное исключение: %s", update, exc_info=context.error)


application.add_error_handler(error_handler)

# ---------- кэш тегов при старте ----------
active_tags = get_active_tags()
tag_storage.load_from([t['name'] for t in active_tags])

alias_rows = get_all_tag_aliases()
tag_storage.load_aliases([(row['alias'], row['name']) for row in alias_rows])

# ---------- служебные ----------
application.add_handler(ChatMemberHandler(track_bot_membership, ChatMemberHandler.MY_CHAT_MEMBER))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, track_member_left))

# ---------- язык ----------
application.add_handler(CommandHandler('language', language_command))

# ---------- дни рождения пользователей (старая chat_id-модель) ----------
application.add_handler(CommandHandler('setbirthday', set_birthday_command))
application.add_handler(CommandHandler('mybirthday', my_birthday_command))
application.add_handler(CommandHandler('deletebirthday', delete_birthday_command))

admin_birthday_conv = ConversationHandler(
    entry_points=[CommandHandler('admin_birthdays', start_admin_birthday, filters=filters.ChatType.PRIVATE)],
    states={
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
application.job_queue.run_daily(send_retention_warnings, time=time(hour=10, minute=0, tzinfo=MOSCOW_TZ))
application.job_queue.run_daily(run_retention_cleanup, time=time(hour=10, minute=30, tzinfo=MOSCOW_TZ))
application.job_queue.run_daily(check_character_birthdays, time=time(hour=9, minute=15, tzinfo=MOSCOW_TZ))

# ---------- подписки ----------
application.add_handler(CommandHandler('mysub', my_subscriptions))
application.add_handler(CommandHandler('sub', subscribe))
application.add_handler(CommandHandler('unsub', unsubscribe))
application.add_handler(CommandHandler('unsuball', unsuball_command))
application.add_handler(CallbackQueryHandler(unsuball_confirm_callback, pattern=r'^unsuballconfirm:'))

# ---------- теги (админ) ----------
application.add_handler(CommandHandler('all', list_all_tags_command))
application.add_handler(CommandHandler('rename', rename_tag_command))
application.add_handler(CommandHandler('delete_tag', delete_tag_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('block_tag', block_tag_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('restore_tag', restore_tag_command, filters=filters.ChatType.PRIVATE))

# ---------- добавление алиаса ----------
application.add_handler(CommandHandler('addtag', addtag_command))
application.add_handler(CallbackQueryHandler(addtag_confirm_callback, pattern=r'^addtagconfirm:'))

# ---------- профиль ----------
application.add_handler(CommandHandler('updateme', update_me))

# ---------- тегирование на фото ----------
application.add_handler(CommandHandler('tag', tag_command))
application.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.CAPTION, media_tag_handler))
# ---------- inline ----------
application.add_handler(InlineQueryHandler(inline_search))

# ---------- callback-и тегов (ветка del убрана на Этапе B1) ----------
application.add_handler(CallbackQueryHandler(callback_router, pattern=r'^(subscribe|tag|new)/'))

# ---------- роли ----------
application.add_handler(CommandHandler('add_role', add_role_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('remove_role', remove_role_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('list_roles', list_roles_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('backfill_cards', backfill_cards_command, filters=filters.ChatType.PRIVATE))

reroll_conv = ConversationHandler(
    entry_points=[CommandHandler('reroll_role', start_reroll_role, filters=filters.ChatType.PRIVATE)],
    states={
        WAITING_REROLL_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_reroll_forward)],
    },
    fallbacks=[],
)
application.add_handler(reroll_conv)

# ---------- игры ----------
application.add_handler(CommandHandler('mygames', mygames_command))
application.add_handler(CallbackQueryHandler(toggle_game_callback, pattern=r'^gametoggle:'))
application.add_handler(CallbackQueryHandler(games_done_callback, pattern=r'^gamesdone$'))

# ---------- статистика ----------
application.add_handler(CommandHandler('tagstats', tagstats_command))

# ---------- Заявки ----------
character_request_conv = ConversationHandler(
    entry_points=[CommandHandler('newcharacter', start_character_request)],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
        ASK_BIRTHDATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_birthdate)],
        ASK_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_description)],
        ASK_PHOTO: [MessageHandler(filters.PHOTO, ask_photo)],
    },
    fallbacks=[CommandHandler('cancel', cancel_character_request)],
)
application.add_handler(character_request_conv)

character_review_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(character_request_action_callback, pattern=r'^charreqaction:')],
    states={
        EDITING_FIELD: [CallbackQueryHandler(choose_charreq_edit_field, pattern=r'^charreqedit:')],
        EDITING_VALUE: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, receive_charreq_edit_value)],
    },
    fallbacks=[],
)
application.add_handler(character_review_conv)

character_edit_conv = ConversationHandler(
    entry_points=[CommandHandler('editcharacter', start_character_edit)],
    states={
        CHOOSE_CHARACTER: [CallbackQueryHandler(pick_character, pattern=r'^editcharpick:')],
        CHOOSE_FIELD: [CallbackQueryHandler(choose_field, pattern=r'^editcharfield:')],
        WAITING_VALUE: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, receive_edit_value)],
    },
    fallbacks=[CommandHandler('cancel', cancel_character_edit)],
)
application.add_handler(character_edit_conv)

application.add_handler(CommandHandler('mycharrequests', my_character_requests))

application.add_handler(CommandHandler('setprimary', setprimary_command))
application.add_handler(CallbackQueryHandler(setprimary_callback, pattern=r'^setprimary:'))

admin_setprimary_conv = ConversationHandler(
    entry_points=[CommandHandler('set_primary_character', start_admin_setprimary, filters=filters.ChatType.PRIVATE)],
    states={
        WAITING_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_admin_setprimary_forward)],
        CHOOSING_CHARACTER: [CallbackQueryHandler(admin_setprimary_callback, pattern=r'^adminsetprimary:')],
    },
    fallbacks=[],
)
application.add_handler(admin_setprimary_conv)

card_request_conv = ConversationHandler(
    entry_points=[CommandHandler('editcard', start_card_request)],
    states={
        WAITING_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bio)],
    },
    fallbacks=[CommandHandler('cancel', cancel_card_request)],
)
application.add_handler(card_request_conv)
application.add_handler(CommandHandler('mycardrequest', my_card_requests))

card_review_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(card_request_action_callback, pattern=r'^cardreqaction:')],
    states={
        EDITING_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_card_edit_bio)],
    },
    fallbacks=[],
)
application.add_handler(card_review_conv)

application.add_handler(CommandHandler('card', card_command))

add_admin_conv = ConversationHandler(
    entry_points=[CommandHandler('add_admin', start_add_admin, filters=filters.ChatType.PRIVATE)],
    states={WAITING_ADD_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_add_forward)]},
    fallbacks=[],
)
application.add_handler(add_admin_conv)

remove_admin_conv = ConversationHandler(
    entry_points=[CommandHandler('remove_admin', start_remove_admin, filters=filters.ChatType.PRIVATE)],
    states={WAITING_REMOVE_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_remove_forward)]},
    fallbacks=[],
)
application.add_handler(remove_admin_conv)

application.add_handler(CommandHandler('list_admins', list_admins_command))
application.add_handler(CommandHandler('pendingrequests', pending_requests_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('myclaimedrequests', my_claimed_requests_command, filters=filters.ChatType.PRIVATE))
# ============================================================
# ОТКЛЮЧЕНО (используют старую объединённую character-модель,
# сломаются при вызове; ждут переработки на Этапах D/E):
#   - handlers/character_requests.py  (заявки на персонажа)
#   - handlers/admin_requests.py      (рассмотрение заявок админом)
#   - handlers/view_characters.py     (/mycharacters, /character @nick)
#   - handlers/card.py                (/card)
#   - handlers/admin_edit_character.py (/edit_character) — НЕ БЫЛ
#     отключён на Этапе A, исправлено сейчас (Этап B1 sync-проверка)
# ============================================================

logger.info("Бот запущен")
application.run_polling()