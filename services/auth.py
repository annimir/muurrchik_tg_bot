from database.queries import get_user_by_tg_id, create_user, update_user_tag


async def auth(user_id: int, user_tag: str | None):
    """
    ИСПРАВЛЕНО: убран вызов resolve_pending_owner_links() — эта функция
    была частью Google Sheets-интеграции (Этап 7 старого плана),
    удалённой на Этапе A. Таблица pending_owner_links и сама концепция
    "отложенной привязки персонажа по юзернейму" больше не существуют.
    """
    user = get_user_by_tg_id(user_id)

    if not user:
        create_user(user_id, user_tag)
        user = get_user_by_tg_id(user_id)
    elif user['tag'] != user_tag:
        update_user_tag(user_id, user_tag)
        user = get_user_by_tg_id(user_id)

    return user