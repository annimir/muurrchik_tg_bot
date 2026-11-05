import re
from urllib.parse import parse_qs, urljoin, urlsplit

import httpx

YOUTUBE_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{11}$')
TIKTOK_ID_PATTERN = re.compile(r'^\d{10,25}$')
INSTAGRAM_CODE_PATTERN = re.compile(r'^[A-Za-z0-9_-]{5,40}$')
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _embed(platform, url, *, vertical=False, resolve=False):
    return {
        'platform': platform,
        'platform_name': platform.capitalize(),
        'url': url,
        'vertical': vertical,
        'resolve': resolve,
    }


def _youtube_embed(parts):
    host = (parts.hostname or '').lower()
    path = [segment for segment in parts.path.split('/') if segment]
    video_id = None
    if host in {'youtu.be', 'www.youtu.be'} and path:
        video_id = path[0]
    elif host in {'youtube.com', 'www.youtube.com', 'm.youtube.com'}:
        if path == ['watch']:
            video_id = parse_qs(parts.query).get('v', [None])[0]
        elif len(path) == 2 and path[0] in {'shorts', 'embed', 'live'}:
            video_id = path[1]
    if not video_id or not YOUTUBE_ID_PATTERN.fullmatch(video_id):
        return None
    return _embed(
        'youtube', f'https://www.youtube-nocookie.com/embed/{video_id}?autoplay=1&rel=0',
    )


def _tiktok_embed(parts, usage_id):
    host = (parts.hostname or '').lower()
    path = [segment for segment in parts.path.split('/') if segment]
    if host in {'vm.tiktok.com', 'vt.tiktok.com'} or (
        host in {'tiktok.com', 'www.tiktok.com'} and len(path) == 2 and path[0] == 't'
    ):
        resolver_url = f'/media/embed/{usage_id}' if usage_id else None
        return _embed('tiktok', resolver_url, vertical=True, resolve=True)
    if host not in {'tiktok.com', 'www.tiktok.com'}:
        return None
    for index, segment in enumerate(path[:-1]):
        if segment in {'video', 'photo'} and TIKTOK_ID_PATTERN.fullmatch(path[index + 1]):
            return _embed(
                'tiktok',
                f'https://www.tiktok.com/player/v1/{path[index + 1]}?autoplay=1',
                vertical=True,
            )
    return None


def _instagram_embed(parts, usage_id):
    host = (parts.hostname or '').lower()
    path = [segment for segment in parts.path.split('/') if segment]
    if host in {'instagr.am', 'www.instagr.am'} and path:
        resolver_url = f'/media/embed/{usage_id}' if usage_id else None
        return _embed('instagram', resolver_url, vertical=True, resolve=True)
    if host not in {'instagram.com', 'www.instagram.com'} or len(path) < 2:
        return None
    kind, code = path[0], path[1]
    if kind == 'reels':
        kind = 'reel'
    if kind not in {'reel', 'p', 'tv'} or not INSTAGRAM_CODE_PATTERN.fullmatch(code):
        return None
    return _embed(
        'instagram', f'https://www.instagram.com/{kind}/{code}/embed', vertical=True,
    )


def get_video_embed(url, usage_id=None):
    if not url:
        return None
    try:
        parts = urlsplit(url)
        host = (parts.hostname or '').lower()
    except ValueError:
        return None
    if parts.scheme not in {'http', 'https'}:
        return None
    if host in {'youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be', 'www.youtu.be'}:
        return _youtube_embed(parts)
    if host in {'tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'vt.tiktok.com'}:
        return _tiktok_embed(parts, usage_id)
    if host in {'instagram.com', 'www.instagram.com', 'instagr.am', 'www.instagr.am'}:
        return _instagram_embed(parts, usage_id)
    return None


async def resolve_video_embed(url):
    current_url = url
    initial = get_video_embed(url)
    if not initial:
        return None
    if not initial['resolve']:
        return initial

    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        headers={'User-Agent': 'Mozilla/5.0 (compatible; PaimonMediaEmbed/1.0)'},
    ) as client:
        for _ in range(5):
            embed = get_video_embed(current_url)
            if not embed or embed['platform'] != initial['platform']:
                return None
            if not embed['resolve']:
                return embed
            async with client.stream('GET', current_url) as response:
                if response.status_code not in REDIRECT_STATUSES:
                    return None
                location = response.headers.get('location')
            if not location:
                return None
            current_url = urljoin(current_url, location)
    return None
