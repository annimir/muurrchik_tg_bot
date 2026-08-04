import asyncio
from database.queries import (
    get_user_by_tg_id, create_user, update_user_tag, resolve_pending_owner_links,
)

async def auth(user_id: int, user_tag: str | None):
    user = get_user_by_tg_id(user_id)

    if not user:
        create_user(user_id, user_tag)
        if user_tag:
            resolve_pending_owner_links(user_tag, user_id)  # добавили
        user = get_user_by_tg_id(user_id)
    elif user['tag'] != user_tag:
        update_user_tag(user_id, user_tag)
        if user_tag:
            resolve_pending_owner_links(user_tag, user_id)  # добавили
        user = get_user_by_tg_id(user_id)

    return user