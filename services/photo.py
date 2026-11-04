from pathlib import Path

from telegram import InputFile

from config.config import config

LOCAL_PHOTO_PREFIX = 'local:'


def photo_input(file_id):
    if file_id and not isinstance(file_id, Path) and file_id.startswith(LOCAL_PHOTO_PREFIX):
        filename = Path(file_id.removeprefix(LOCAL_PHOTO_PREFIX)).name
        file_id = Path(config.web_media_cache_dir) / 'uploads' / filename
    if isinstance(file_id, Path):
        return InputFile(file_id.read_bytes(), filename=file_id.name, attach=True)
    return file_id
