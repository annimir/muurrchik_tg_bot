from telegram import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

GROUP_COMMANDS_RU = [
    BotCommand("sub", "Подписаться на тег"),
    BotCommand("unsub", "Отписаться от тега"),
    BotCommand("unsuball", "Отписаться от всех тегов"),
    BotCommand("mysub", "Мои подписки"),
    BotCommand("addtag", "Добавить алиас существующему тегу"),
    BotCommand("tag", "Позвать подписчиков тега"),
    BotCommand("tagstats", "Статистика тега"),
    BotCommand("all", "Список всех тегов"),
    BotCommand("rename", "Переименовать тег (админ)"),
    BotCommand("setbirthday", "Указать день рождения"),
    BotCommand("mybirthday", "Мой день рождения"),
    BotCommand("deletebirthday", "Удалить мой день рождения"),
    BotCommand("updateme", "Обновить мой юзернейм в базе"),
    BotCommand("mygames", "Выбрать игры, в которые играю"),
    BotCommand("card", "Моя карточка (или /card @nickname)"),
    BotCommand("setprimary", "Сменить основного персонажа"),
    BotCommand("newcharacter", "Подать заявку на персонажа"),
    BotCommand("editcharacter", "Изменить своего персонажа"),
    BotCommand("mycharrequests", "Мои заявки на персонажей"),
    BotCommand("editcard", "Изменить текст карточки"),
    BotCommand("mycardrequest", "Мои заявки на карточку"),
    BotCommand("language", "Сменить язык бота (RU/EN)"),
]

GROUP_COMMANDS_EN = [
    BotCommand("sub", "Subscribe to a tag"),
    BotCommand("unsub", "Unsubscribe from a tag"),
    BotCommand("unsuball", "Unsubscribe from all tags"),
    BotCommand("mysub", "My subscriptions"),
    BotCommand("addtag", "Add an alias to an existing tag"),
    BotCommand("tag", "Mention a tag's subscribers"),
    BotCommand("tagstats", "Tag statistics"),
    BotCommand("all", "List all tags"),
    BotCommand("rename", "Rename a tag (admin)"),
    BotCommand("setbirthday", "Set your birthday"),
    BotCommand("mybirthday", "My birthday"),
    BotCommand("deletebirthday", "Delete my birthday"),
    BotCommand("updateme", "Refresh my username in the database"),
    BotCommand("mygames", "Choose which games you play"),
    BotCommand("card", "My card (or /card @nickname)"),
    BotCommand("setprimary", "Switch your primary character"),
    BotCommand("newcharacter", "Submit a character request"),
    BotCommand("editcharacter", "Edit your character"),
    BotCommand("mycharrequests", "My character requests"),
    BotCommand("editcard", "Edit your card text"),
    BotCommand("mycardrequest", "My card requests"),
    BotCommand("language", "Change bot language (RU/EN)"),
]

PRIVATE_COMMANDS_RU = GROUP_COMMANDS_RU + [
    BotCommand("delete_tag", "Скрыть тег (админ)"),
    BotCommand("block_tag", "Заблокировать тег (админ)"),
    BotCommand("restore_tag", "Восстановить тег (админ)"),
    BotCommand("add_game", "Добавить игру в список (админ)"),
    BotCommand("remove_game", "Удалить игру из списка (админ)"),
    BotCommand("list_games", "Список игр (админ)"),
    BotCommand("set_primary_character", "Сменить основного персонажа за пользователя (админ)"),
    BotCommand("add_admin", "Добавить администратора (админ)"),
    BotCommand("remove_admin", "Удалить администратора (админ)"),
    BotCommand("list_admins", "Список администраторов (админ)"),
    BotCommand("pendingrequests", "Заявки, ожидающие взятия в работу (админ)"),
    BotCommand("myclaimedrequests", "Мои заявки в работе (админ)"),
    BotCommand("admin_birthdays", "Управление днями рождения (админ)"),
    BotCommand("cancel", "Отменить текущий диалог"),
]

PRIVATE_COMMANDS_EN = GROUP_COMMANDS_EN + [
    BotCommand("delete_tag", "Hide a tag (admin)"),
    BotCommand("block_tag", "Block a tag (admin)"),
    BotCommand("restore_tag", "Restore a tag (admin)"),
    BotCommand("add_game", "Add a game to the list (admin)"),
    BotCommand("remove_game", "Remove a game from the list (admin)"),
    BotCommand("list_games", "List games (admin)"),
    BotCommand("set_primary_character", "Switch a user's primary character (admin)"),
    BotCommand("add_admin", "Add an administrator (admin)"),
    BotCommand("remove_admin", "Remove an administrator (admin)"),
    BotCommand("list_admins", "List administrators (admin)"),
    BotCommand("pendingrequests", "Requests waiting to be picked up (admin)"),
    BotCommand("myclaimedrequests", "My requests in progress (admin)"),
    BotCommand("admin_birthdays", "Manage birthdays (admin)"),
    BotCommand("cancel", "Cancel the current dialog"),
]


async def register_bot_commands(application):
    await application.bot.set_my_commands(GROUP_COMMANDS_RU, scope=BotCommandScopeAllGroupChats())
    await application.bot.set_my_commands(GROUP_COMMANDS_EN, scope=BotCommandScopeAllGroupChats(), language_code="en")
    await application.bot.set_my_commands(PRIVATE_COMMANDS_RU, scope=BotCommandScopeAllPrivateChats())
    await application.bot.set_my_commands(PRIVATE_COMMANDS_EN, scope=BotCommandScopeAllPrivateChats(), language_code="en")