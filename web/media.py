import asyncio
import hashlib
import json
import mimetypes
import os
from pathlib import Path

import httpx
from fastapi import HTTPException
from fastapi.responses import FileResponse

from config.config import config


class TelegramMediaStore:
    def __init__(self, cache_dir, bot_token):
        self.cache_dir = Path(cache_dir)
        self.bot_token = bot_token
        self._lock = asyncio.Lock()

    def _find_cached(self, digest):
        if not self.cache_dir.exists():
            return None
        return next(
            (path for path in self.cache_dir.glob(f'{digest}.*') if path.suffix not in {'.json', '.download'}),
            None,
        )

    async def get_response(self, file_id, cache_key):
        digest = hashlib.sha256(file_id.encode()).hexdigest()
        existing = self._find_cached(digest)
        if existing and existing.suffix != '.json':
            return self._file_response(existing)

        async with self._lock:
            existing = self._find_cached(digest)
            if existing and existing.suffix != '.json':
                return self._file_response(existing)
            path = await self._download(file_id, digest, cache_key)
        return self._file_response(path)

    async def get_profile_photo_file_id(self, tg_id):
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            response = await client.get(
                f'https://api.telegram.org/bot{self.bot_token}/getUserProfilePhotos',
                params={'user_id': tg_id, 'limit': 1},
            )
            response.raise_for_status()
            payload = response.json()
        if not payload.get('ok') or not payload['result']['total_count']:
            return None
        return payload['result']['photos'][0][-1]['file_id']

    async def _download(self, file_id, digest, cache_key):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            response = await client.get(
                f'https://api.telegram.org/bot{self.bot_token}/getFile',
                params={'file_id': file_id},
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get('ok'):
                raise HTTPException(status_code=404, detail='Файл не найден')
            telegram_path = payload['result']['file_path']
            suffix = Path(telegram_path).suffix[:12]
            path = self.cache_dir / f'{digest}{suffix}'
            temporary = self.cache_dir / f'{digest}.download'
            size = 0
            async with client.stream(
                'GET', f'https://api.telegram.org/file/bot{self.bot_token}/{telegram_path}',
            ) as download:
                download.raise_for_status()
                with temporary.open('wb') as output:
                    async for chunk in download.aiter_bytes():
                        size += len(chunk)
                        if size > 100 * 1024 * 1024:
                            output.close()
                            temporary.unlink(missing_ok=True)
                            raise HTTPException(status_code=413, detail='Файл слишком большой')
                        output.write(chunk)
            os.replace(temporary, path)
            media_type = download.headers.get('content-type') or mimetypes.guess_type(path.name)[0]
            path.with_suffix(path.suffix + '.json').write_text(
                json.dumps({'media_type': media_type or 'application/octet-stream', 'name': cache_key}),
                encoding='utf-8',
            )
        return path

    def _file_response(self, path):
        metadata_path = path.with_suffix(path.suffix + '.json')
        media_type = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding='utf-8'))
            media_type = metadata.get('media_type', media_type)
        return FileResponse(path, media_type=media_type, headers={'Cache-Control': 'public, max-age=86400'})


_media_store = None


def get_media_store():
    global _media_store
    if _media_store is None:
        _media_store = TelegramMediaStore(config.web_media_cache_dir, config.bot_token)
    return _media_store
