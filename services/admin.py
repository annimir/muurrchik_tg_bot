from database.queries import get_all_admin_ids


def is_admin(user_id: int) -> bool:
    return int(user_id) in get_all_admin_ids()