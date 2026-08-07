import logging
import random

from database.queries import get_all_flavor_roles, set_user_flavor_role

logger = logging.getLogger(__name__)


def assign_random_role(user_id, exclude_role_id: int | None = None) -> str | None:
    """
    Назначает случайную роль. exclude_role_id — исключить конкретную роль из выбора
    (используется при /reroll_role, чтобы гарантированно сменить роль на другую).
    Возвращает имя назначенной роли, либо None, если ролей нет вообще.
    """
    roles = get_all_flavor_roles()

    if exclude_role_id is not None and len(roles) > 1:
        roles = [r for r in roles if r['id'] != exclude_role_id]

    if not roles:
        logger.warning("Список ролей пуст — не могу назначить роль пользователю %s", user_id)
        set_user_flavor_role(user_id, None)
        return None

    role = random.choice(roles)
    set_user_flavor_role(user_id, role['id'])
    return role['name']