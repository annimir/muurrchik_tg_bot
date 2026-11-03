from pathlib import Path

from config.config import config

LOCAL_PHOTO_PREFIX = 'local:'


def photo_input(file_id):
    if isinstance(file_id, Path):
        return file_id
    if file_id and file_id.startswith(LOCAL_PHOTO_PREFIX):
        return Path(config.web_media_cache_dir) / 'uploads' / Path(file_id).name
    return file_id
