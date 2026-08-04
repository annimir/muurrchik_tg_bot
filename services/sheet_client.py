import logging
import re

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
IMAGE_FORMULA_PATTERN = re.compile(r'=IMAGE\("([^"]+)"', re.IGNORECASE)


def _get_service():
    credentials = service_account.Credentials.from_service_account_file(
        config.google_sheets_credentials_path, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=credentials)


def _extract_image_url(cell_value: str | None) -> str | None:
    if not cell_value:
        return None
    match = IMAGE_FORMULA_PATTERN.search(cell_value)
    return match.group(1) if match else None


def fetch_sheet_rows() -> list[dict]:
    service = _get_service()
    spreadsheet_id = config.google_sheets_spreadsheet_id
    sheet_name = config.google_sheets_sheet_name

    result = service.spreadsheets().values().get(
        spreadsheetId=spreadsheet_id,
        range=f"{sheet_name}!A3:I1000",
        valueRenderOption="FORMULA",  # чтобы получить =IMAGE("url") как текст, а не рендер
    ).execute()

    raw_rows = result.get("values", [])
    rows = []

    for raw_row in raw_rows:
        raw_row = raw_row + [""] * (9 - len(raw_row))  # добиваем до 9 колонок

        rows.append({
            "characters": [
                {"name": raw_row[1].strip(), "photo_url": _extract_image_url(raw_row[0])},
                {"name": raw_row[3].strip(), "photo_url": _extract_image_url(raw_row[2])},
                {"name": raw_row[5].strip(), "photo_url": _extract_image_url(raw_row[4])},
            ],
            "tg_username": raw_row[6].lstrip("@").strip(),
            "affiliation": raw_row[7].strip() if raw_row[7] not in ("-", "") else None,
            "position": raw_row[8].strip() if raw_row[8] not in ("-", "") else None,
        })

    logger.info("Получено %d строк из Google Таблицы", len(rows))
    return rows