PAIMON_COMMAND_GROUPS = [
    {
        'name': 'Теги и подписки',
        'description': 'Поиск материалов, упоминания и уведомления по интересующим тегам.',
        'commands': [
            {'usage': '/sub <тег>', 'description': 'Подписаться на уведомления по тегу.'},
            {'usage': '/unsub <тег>', 'description': 'Отписаться от уведомлений по тегу.'},
            {'usage': '/unsuball', 'description': 'Отписаться от всех тегов после подтверждения.'},
            {'usage': '/mysub', 'description': 'Показать список активных подписок.'},
            {'usage': '/tag <теги>', 'description': 'Позвать подписчиков одного или нескольких тегов.'},
            {'usage': '/tagstats <тег>', 'description': 'Посмотреть статистику использования тега.'},
            {'usage': '/all', 'description': 'Показать список всех тегов.'},
            {'usage': '/addtag <тег> <алиас>', 'description': 'Предложить алиас для существующего тега.'},
        ],
    },
    {
        'name': 'Профиль и персонажи',
        'description': 'Карточки игроков, персонажи и заявки на изменение информации.',
        'commands': [
            {'usage': '/card [@username]', 'description': 'Открыть свою карточку или карточку другого игрока.'},
            {'usage': '/updateme', 'description': 'Обновить свой Telegram username в профиле.'},
            {'usage': '/setprimary', 'description': 'Выбрать основного персонажа.'},
            {'usage': '/newcharacter', 'description': 'Подать заявку на создание персонажа.'},
            {'usage': '/editcharacter', 'description': 'Отправить заявку на изменение персонажа.'},
            {'usage': '/mycharrequests', 'description': 'Посмотреть свои заявки на персонажей.'},
            {'usage': '/editcard', 'description': 'Отправить заявку на изменение описания игрока.'},
            {'usage': '/mycardrequest', 'description': 'Посмотреть свои заявки на изменение карточки.'},
        ],
    },
    {
        'name': 'Игры, дни рождения и язык',
        'description': 'Личные настройки и информация, которая отображается в профиле.',
        'commands': [
            {'usage': '/mygames', 'description': 'Выбрать игры, в которые вы играете.'},
            {'usage': '/setbirthday <ДД.ММ>', 'description': 'Указать день рождения игрока.'},
            {'usage': '/mybirthday', 'description': 'Показать сохранённый день рождения.'},
            {'usage': '/deletebirthday', 'description': 'Удалить свой день рождения.'},
            {'usage': '/language <RU|EN>', 'description': 'Изменить язык ответов бота.'},
        ],
    },
    {
        'name': 'Административные команды',
        'description': 'Эти команды доступны только администраторам, большинство — в личном чате с ботом.',
        'admin': True,
        'commands': [
            {'usage': '/rename', 'description': 'Переименовать тег.'},
            {'usage': '/delete_tag', 'description': 'Скрыть тег из активного использования.'},
            {'usage': '/block_tag', 'description': 'Заблокировать тег.'},
            {'usage': '/restore_tag', 'description': 'Восстановить скрытый или заблокированный тег.'},
            {'usage': '/add_game', 'description': 'Добавить игру в общий список.'},
            {'usage': '/remove_game', 'description': 'Удалить игру из общего списка.'},
            {'usage': '/list_games', 'description': 'Показать список игр.'},
            {'usage': '/add_position', 'description': 'Добавить должность персонажа.'},
            {'usage': '/remove_position', 'description': 'Удалить должность из списка.'},
            {'usage': '/list_positions', 'description': 'Показать должности и их владельцев.'},
            {'usage': '/assign_position', 'description': 'Назначить должность персонажу.'},
            {'usage': '/revoke_position', 'description': 'Снять должность с персонажа.'},
            {'usage': '/add_affiliation', 'description': 'Добавить принадлежность в дерево.'},
            {'usage': '/remove_affiliation', 'description': 'Удалить принадлежность и её дочерние ветви.'},
            {'usage': '/list_affiliations', 'description': 'Показать дерево принадлежностей.'},
            {'usage': '/assign_affiliation', 'description': 'Назначить принадлежность персонажу.'},
            {'usage': '/set_primary_character', 'description': 'Сменить основного персонажа другого игрока.'},
            {'usage': '/pendingrequests', 'description': 'Показать заявки, ожидающие обработки.'},
            {'usage': '/myclaimedrequests', 'description': 'Показать заявки, взятые вами в работу.'},
            {'usage': '/admin_birthdays', 'description': 'Управлять днями рождения игроков.'},
            {'usage': '/add_admin', 'description': 'Назначить нового администратора.'},
            {'usage': '/remove_admin', 'description': 'Снять права администратора.'},
            {'usage': '/list_admins', 'description': 'Показать список администраторов.'},
            {'usage': '/cancel', 'description': 'Отменить текущий диалог с ботом.'},
        ],
    },
]


def get_paimon_command_groups():
    return PAIMON_COMMAND_GROUPS


def get_paimon_command_count():
    return sum(len(group['commands']) for group in PAIMON_COMMAND_GROUPS)
