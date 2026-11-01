import logging
from datetime import time
from zoneinfo import ZoneInfo

from telegram.ext import (
    Application, CommandHandler, MessageHandler, InlineQueryHandler,
    CallbackQueryHandler, ChatMemberHandler, ConversationHandler, filters,
)

from config.logging_config import setup_logging
from config.config import config

from database.queries import get_active_tags, get_all_tag_aliases, bootstrap_admin_if_empty
from services.bot_commands import register_bot_commands
from services.tag_storage import tag_storage

from handlers.welcome import welcome_new_member
from handlers.chat_tracking import track_bot_membership
from handlers.membership_tracking import track_member_left
from handlers.language import language_command

from handlers.birthday import set_birthday_command, my_birthday_command, delete_birthday_command
from handlers.birthday_job import check_birthdays
from handlers.character_birthday_job import check_character_birthdays
from handlers.birthday_admin_dm import (
    start_admin_birthday, main_menu_router, receive_forward,
    select_existing_user, manage_entry_router, go_back, receive_date, cancel,
    MAIN_MENU, WAITING_FORWARD, WAITING_DATE, MANAGING_ENTRY,
)
from handlers.retention_job import send_retention_warnings, run_retention_cleanup

from handlers.subscriptions import my_subscriptions, subscribe, unsubscribe
from handlers.unsuball import unsuball_command, unsuball_confirm_callback

from handlers.tags_admin import (
    list_all_tags_command, rename_tag_command,
    delete_tag_command, block_tag_command, restore_tag_command,
)
from handlers.addtag import addtag_command, addtag_confirm_callback
from handlers.tag_stats import tagstats_command

from handlers.user_profile import update_me
from handlers.tagging import media_tag_handler, link_tag_handler, tag_command
from handlers.inline_search import inline_search
from handlers.callbacks import callback_router

from handlers.admin_roles import (
    add_role_command, remove_role_command, list_roles_command,
    start_reroll_role, receive_reroll_forward, WAITING_REROLL_FORWARD,
    backfill_cards_command, start_set_role, receive_set_role_forward, choose_specific_role,
    WAITING_SETROLE_FORWARD, CHOOSING_SPECIFIC_ROLE,
)
from handlers.games import mygames_command, toggle_game_callback, games_done_callback
from handlers.admin_games import add_game_command, remove_game_command, list_games_command

from handlers.character_requests import (
    start_character_request, ask_name, ask_birthdate, ask_description, ask_photo,
    cancel_character_request, my_character_requests,
    ASK_NAME, ASK_BIRTHDATE, ASK_DESCRIPTION, ASK_PHOTO,
)
from handlers.admin_character_requests import (
    character_request_action_callback, choose_charreq_edit_field, receive_charreq_edit_value,
    EDITING_FIELD, EDITING_VALUE,
)
from handlers.character_edit import (
    start_character_edit, pick_character, choose_field, receive_edit_value, cancel_character_edit,
    CHOOSE_CHARACTER, CHOOSE_FIELD, WAITING_VALUE,
)
from handlers.character_primary import setprimary_command, setprimary_callback
from handlers.admin_character_primary import (
    start_admin_setprimary, receive_admin_setprimary_forward, admin_setprimary_callback,
    WAITING_FORWARD as ADMIN_SETPRIMARY_WAITING_FORWARD, CHOOSING_CHARACTER,
)

from handlers.card import card_command
from handlers.card_request import (
    start_card_request, receive_bio, cancel_card_request, my_card_requests,
    WAITING_BIO,
)
from handlers.admin_positions import (
    add_position_command, remove_position_command, list_positions_command,
    start_assign_position, choose_position_for_assign, receive_assign_position_forward,
    choose_character_for_position, start_revoke_position, choose_revoke_position,
    CHOOSING_POSITION, WAITING_ASSIGN_FORWARD, CHOOSING_CHARACTER_FOR_POSITION, CHOOSING_REVOKE_POSITION,
)
from handlers.admin_affiliations import (
    start_add_affiliation, choose_affiliation_type, choose_affiliation_parent, receive_affiliation_name,
    start_remove_affiliation, choose_affiliation_to_remove, list_affiliations_command,
    start_assign_affiliation, choose_affiliation_for_assign, receive_assign_affiliation_forward,
    choose_character_for_affiliation,
    CHOOSING_TYPE, CHOOSING_PARENT, WAITING_NAME, CHOOSING_REMOVE,
    CHOOSING_AFF_FOR_ASSIGN, WAITING_AFF_ASSIGN_FORWARD, CHOOSING_CHARACTER_FOR_AFF,
)
from handlers.admin_role_edit import (
    start_edit_role, choose_role_to_edit, choose_role_field, receive_role_field_value,
    CHOOSING_ROLE, CHOOSING_FIELD, WAITING_VALUE as ADMIN_ROLE_WAITING_VALUE,
)
from handlers.admin_card_requests import (
    card_request_action_callback, receive_card_edit_bio, EDITING_BIO,
)

from handlers.admin_management import (
    start_add_admin, receive_add_forward, start_remove_admin, receive_remove_forward,
    list_admins_command, WAITING_ADD_FORWARD, WAITING_REMOVE_FORWARD,
)
from handlers.admin_request_queue import pending_requests_command, my_claimed_requests_command

setup_logging()
logger = logging.getLogger(__name__)

application = Application.builder().token(config.bot_token).post_init(register_bot_commands).build()


async def error_handler(update, context):
    update_id = getattr(update, 'update_id', None)
    logger.error("Необработанное исключение (update_id=%s)", update_id, exc_info=context.error)


application.add_error_handler(error_handler)

# ---------- bootstrap ----------
bootstrap_admin_if_empty(config.admin_user_id)

active_tags = get_active_tags()
tag_storage.load_from([t['name'] for t in active_tags])
alias_rows = get_all_tag_aliases()
tag_storage.load_aliases([(row['alias'], row['name']) for row in alias_rows])

MOSCOW_TZ = ZoneInfo('Europe/Moscow')

# ---------- служебные ----------
application.add_handler(ChatMemberHandler(track_bot_membership, ChatMemberHandler.MY_CHAT_MEMBER))
application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_member))
application.add_handler(MessageHandler(filters.StatusUpdate.LEFT_CHAT_MEMBER, track_member_left))

# ---------- язык ----------
application.add_handler(CommandHandler('language', language_command))

# ---------- дни рождения пользователей ----------
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

application.job_queue.run_daily(check_birthdays, time=time(hour=9, minute=0, tzinfo=MOSCOW_TZ))
application.job_queue.run_daily(check_character_birthdays, time=time(hour=9, minute=15, tzinfo=MOSCOW_TZ))
application.job_queue.run_daily(send_retention_warnings, time=time(hour=10, minute=0, tzinfo=MOSCOW_TZ))
application.job_queue.run_daily(run_retention_cleanup, time=time(hour=10, minute=30, tzinfo=MOSCOW_TZ))

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

application.add_handler(CommandHandler('addtag', addtag_command))
application.add_handler(CallbackQueryHandler(addtag_confirm_callback, pattern=r'^addtagconfirm:'))

application.add_handler(CommandHandler('tagstats', tagstats_command))

# ---------- профиль ----------
application.add_handler(CommandHandler('updateme', update_me))

# ---------- тегирование ----------
application.add_handler(CommandHandler('tag', tag_command))
application.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO) & filters.CAPTION, media_tag_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, link_tag_handler), group=1)

# ---------- inline ----------
application.add_handler(InlineQueryHandler(inline_search))

# ---------- callback-и тегов ----------
application.add_handler(CallbackQueryHandler(callback_router, pattern=r'^(subscribe|tag|new)/'))

# ---------- роли ----------
application.add_handler(CommandHandler('add_role', add_role_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('remove_role', remove_role_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('list_roles', list_roles_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('backfill_cards', backfill_cards_command, filters=filters.ChatType.PRIVATE))

reroll_conv = ConversationHandler(
    entry_points=[CommandHandler('reroll_role', start_reroll_role, filters=filters.ChatType.PRIVATE)],
    states={WAITING_REROLL_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_reroll_forward)]},
    fallbacks=[],
)
application.add_handler(reroll_conv)

setrole_conv = ConversationHandler(
    entry_points=[CommandHandler('set_role', start_set_role, filters=filters.ChatType.PRIVATE)],
    states={
        WAITING_SETROLE_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_set_role_forward)],
        CHOOSING_SPECIFIC_ROLE: [CallbackQueryHandler(choose_specific_role, pattern=r'^setrole:')],
    },
    fallbacks=[],
)
application.add_handler(setrole_conv)

# ---------- игры ----------
application.add_handler(CommandHandler('mygames', mygames_command))
application.add_handler(CallbackQueryHandler(toggle_game_callback, pattern=r'^gametoggle:'))
application.add_handler(CallbackQueryHandler(games_done_callback, pattern=r'^gamesdone$'))

# ---------- заявки на персонажей ----------
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
application.add_handler(CommandHandler('mycharrequests', my_character_requests))

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

application.add_handler(CommandHandler('setprimary', setprimary_command))
application.add_handler(CallbackQueryHandler(setprimary_callback, pattern=r'^setprimary:'))

admin_setprimary_conv = ConversationHandler(
    entry_points=[CommandHandler('set_primary_character', start_admin_setprimary, filters=filters.ChatType.PRIVATE)],
    states={
        ADMIN_SETPRIMARY_WAITING_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_admin_setprimary_forward)],
        CHOOSING_CHARACTER: [CallbackQueryHandler(admin_setprimary_callback, pattern=r'^adminsetprimary:')],
    },
    fallbacks=[],
)
application.add_handler(admin_setprimary_conv)

# ---------- карточка ----------
application.add_handler(CommandHandler('card', card_command))

card_request_conv = ConversationHandler(
    entry_points=[CommandHandler('editcard', start_card_request)],
    states={WAITING_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_bio)]},
    fallbacks=[CommandHandler('cancel', cancel_card_request)],
)
application.add_handler(card_request_conv)
application.add_handler(CommandHandler('mycardrequest', my_card_requests))

card_review_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(card_request_action_callback, pattern=r'^cardreqaction:')],
    states={EDITING_BIO: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_card_edit_bio)]},
    fallbacks=[],
)
application.add_handler(card_review_conv)

# ---------- админы + очередь заявок ----------
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
application.add_handler(CommandHandler('add_game', add_game_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('remove_game', remove_game_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('list_games', list_games_command, filters=filters.ChatType.PRIVATE))

application.add_handler(CommandHandler('add_position', add_position_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('remove_position', remove_position_command, filters=filters.ChatType.PRIVATE))
application.add_handler(CommandHandler('list_positions', list_positions_command, filters=filters.ChatType.PRIVATE))

assign_position_conv = ConversationHandler(
    entry_points=[CommandHandler('assign_position', start_assign_position, filters=filters.ChatType.PRIVATE)],
    states={
        CHOOSING_POSITION: [CallbackQueryHandler(choose_position_for_assign, pattern=r'^posassign:')],
        WAITING_ASSIGN_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_assign_position_forward)],
        CHOOSING_CHARACTER_FOR_POSITION: [CallbackQueryHandler(choose_character_for_position, pattern=r'^posassigncharacter:')],
    },
    fallbacks=[],
)
application.add_handler(assign_position_conv)

revoke_position_conv = ConversationHandler(
    entry_points=[CommandHandler('revoke_position', start_revoke_position, filters=filters.ChatType.PRIVATE)],
    states={
        CHOOSING_REVOKE_POSITION: [CallbackQueryHandler(choose_revoke_position, pattern=r'^posrevoke:')],
    },
    fallbacks=[],
)
application.add_handler(revoke_position_conv)

add_affiliation_conv = ConversationHandler(
    entry_points=[CommandHandler('add_affiliation', start_add_affiliation, filters=filters.ChatType.PRIVATE)],
    states={
        CHOOSING_TYPE: [CallbackQueryHandler(choose_affiliation_type, pattern=r'^afftype:')],
        CHOOSING_PARENT: [CallbackQueryHandler(choose_affiliation_parent, pattern=r'^affparent:')],
        WAITING_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_affiliation_name)],
    },
    fallbacks=[],
)
application.add_handler(add_affiliation_conv)

remove_affiliation_conv = ConversationHandler(
    entry_points=[CommandHandler('remove_affiliation', start_remove_affiliation, filters=filters.ChatType.PRIVATE)],
    states={CHOOSING_REMOVE: [CallbackQueryHandler(choose_affiliation_to_remove, pattern=r'^affremove:')]},
    fallbacks=[],
)
application.add_handler(remove_affiliation_conv)

application.add_handler(CommandHandler('list_affiliations', list_affiliations_command, filters=filters.ChatType.PRIVATE))

assign_affiliation_conv = ConversationHandler(
    entry_points=[CommandHandler('assign_affiliation', start_assign_affiliation, filters=filters.ChatType.PRIVATE)],
    states={
        CHOOSING_AFF_FOR_ASSIGN: [CallbackQueryHandler(choose_affiliation_for_assign, pattern=r'^affassign:')],
        WAITING_AFF_ASSIGN_FORWARD: [MessageHandler(filters.FORWARDED & ~filters.COMMAND, receive_assign_affiliation_forward)],
        CHOOSING_CHARACTER_FOR_AFF: [CallbackQueryHandler(choose_character_for_affiliation, pattern=r'^affassigncharacter:')],
    },
    fallbacks=[],
)
application.add_handler(assign_affiliation_conv)

edit_role_conv = ConversationHandler(
    entry_points=[CommandHandler('edit_role', start_edit_role, filters=filters.ChatType.PRIVATE)],
    states={
        CHOOSING_ROLE: [CallbackQueryHandler(choose_role_to_edit, pattern=r'^roleeditpick:')],
        CHOOSING_FIELD: [CallbackQueryHandler(choose_role_field, pattern=r'^roleeditfield:')],
        ADMIN_ROLE_WAITING_VALUE: [MessageHandler((filters.TEXT | filters.PHOTO) & ~filters.COMMAND, receive_role_field_value)],
    },
    fallbacks=[],
)
application.add_handler(edit_role_conv)

logger.info("Бот запущен")
application.run_polling()