from database.queries import ensure_user


async def auth(user_id: int, user_tag: str | None):
    return ensure_user(user_id, user_tag)
