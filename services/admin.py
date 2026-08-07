from database.queries import get_user_language
from config import config


def admin_lang() -> str:
    return get_user_language(int(config.admin_user_id))


def is_admin(user_id: int) -> bool:
    return int(user_id) == int(config.admin_user_id)