import asyncio
import logging

import httpx
import yt_dlp

logger = logging.getLogger(__name__)

YOUTUBE_API_URL = 'https://www.googleapis.com/youtube/v3'


class YouTubeClient:
    def __init__(self, api_key: str, channel_handle: str):
        self.api_key = api_key
        self.channel_handle = channel_handle
        self._uploads_playlist_id = None

    async def _get(self, endpoint, params, operation):
        try:
            from database.queries import log_youtube_api_request
            log_youtube_api_request(operation)
        except Exception as exc:
            logger.warning('Не удалось записать обращение к YouTube API: %s', exc)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f'{YOUTUBE_API_URL}/{endpoint}',
                params={**params, 'key': self.api_key},
            )
        response.raise_for_status()
        payload = response.json()
        if 'error' in payload:
            raise RuntimeError(payload['error'].get('message', 'YouTube API error'))
        return payload

    async def get_uploads_playlist_id(self):
        if self._uploads_playlist_id:
            return self._uploads_playlist_id

        payload = await self._get(
            'channels',
            {
                'part': 'contentDetails',
                'forHandle': self.channel_handle,
                'maxResults': 1,
            },
            'channels.contentDetails',
        )
        items = payload.get('items', [])
        if not items:
            raise RuntimeError(f'YouTube-канал не найден: {self.channel_handle}')

        self._uploads_playlist_id = items[0]['contentDetails']['relatedPlaylists']['uploads']
        return self._uploads_playlist_id

    async def fetch_latest_uploads(self, limit=10):
        playlist_id = await self.get_uploads_playlist_id()
        payload = await self._get(
            'playlistItems',
            {
                'part': 'snippet',
                'playlistId': playlist_id,
                'maxResults': limit,
            },
            'playlistItems.snippet',
        )

        uploads = []
        for item in payload.get('items', []):
            snippet = item.get('snippet', {})
            video_id = snippet.get('resourceId', {}).get('videoId')
            if not video_id:
                continue
            uploads.append({
                'video_id': video_id,
                'title': snippet.get('title') or 'YouTube',
                'published_at': snippet.get('publishedAt'),
            })
        return uploads


def select_latest_by_kind(uploads, classifications):
    selected = {}
    for upload in uploads:
        kind = classifications.get(upload['video_id'])
        if kind in ('video', 'shorts') and kind not in selected:
            selected[kind] = upload
    return selected


def _classify_video_ids_sync(channel_handle, video_ids):
    requested = set(video_ids)
    classifications = {}
    options = {
        'extract_flat': 'discard_incomplete_playlist',
        'playlistend': max(len(requested), 10),
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }

    for kind, tab in (('video', 'videos'), ('shorts', 'shorts')):
        url = f'https://www.youtube.com/{channel_handle}/{tab}'
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
        for entry in info.get('entries') or []:
            video_id = entry.get('id')
            if video_id not in requested:
                continue
            if entry.get('live_status') in ('is_live', 'is_upcoming'):
                continue
            classifications[video_id] = kind

    return classifications


async def classify_video_ids(channel_handle, video_ids):
    if not video_ids:
        return {}
    return await asyncio.to_thread(_classify_video_ids_sync, channel_handle, video_ids)
