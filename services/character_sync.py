import logging

from database.queries import (
    get_all_characters, upsert_sheet_character, deactivate_missing_sheet_characters,
    get_user_by_username, link_user_character, add_pending_owner_link,
)
from services.sheet_client import fetch_sheet_rows
from services.tag_storage import tag_storage

logger = logging.getLogger(__name__)


def sync_characters_from_sheet():
    rows = fetch_sheet_rows()
    synced_names = []

    for row in rows:
        owner_username = row["tg_username"]
        affiliation = row["affiliation"]
        position = row["position"]

        owner = get_user_by_username(owner_username) if owner_username else None

        for char_data in row["characters"]:
            name = char_data["name"].strip()
            if not name:
                continue

            character_id = upsert_sheet_character(
                name=name,
                photo_url=char_data["photo_url"],
                affiliation=affiliation,
                position=position,
            )
            synced_names.append(name)
            tag_storage.add_to_cache(name)

            if owner:
                link_user_character(owner["id"], character_id, assigned_by=None)
            elif owner_username:
                add_pending_owner_link(owner_username, character_id)
                logger.info(
                    "Персонаж '%s' привязан к @%s отложенно — пользователь ещё не писал боту",
                    name, owner_username,
                )

    deactivated = deactivate_missing_sheet_characters(synced_names)
    logger.info(
        "Синхронизация с таблицей завершена: обработано %d персонажей, деактивировано %d",
        len(synced_names), deactivated,
    )