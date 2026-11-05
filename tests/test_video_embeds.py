import unittest
from unittest.mock import MagicMock, patch

import httpx

from web.video_embeds import get_video_embed, resolve_video_embed


class VideoEmbedTests(unittest.TestCase):
    def test_youtube_urls(self):
        expected = 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?autoplay=1&rel=0'
        for url in (
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ&feature=shared',
            'https://youtu.be/dQw4w9WgXcQ?si=abc',
            'https://m.youtube.com/shorts/dQw4w9WgXcQ',
            'https://www.youtube.com/embed/dQw4w9WgXcQ',
            'https://www.youtube.com/live/dQw4w9WgXcQ',
        ):
            with self.subTest(url=url):
                embed = get_video_embed(url)
                self.assertEqual(embed['url'], expected)
                self.assertFalse(embed['vertical'])
                self.assertFalse(embed['resolve'])

    def test_tiktok_url(self):
        embed = get_video_embed('https://www.tiktok.com/@scout2015/video/6718335390845095173?is_from_webapp=1')

        self.assertEqual(embed['url'], 'https://www.tiktok.com/player/v1/6718335390845095173?autoplay=1')
        self.assertTrue(embed['vertical'])
        self.assertFalse(embed['resolve'])

    def test_instagram_urls(self):
        for kind in ('reel', 'reels', 'p', 'tv'):
            with self.subTest(kind=kind):
                embed = get_video_embed(f'https://www.instagram.com/{kind}/abcDEF_123-/?igsh=abc')
                expected_kind = 'reel' if kind == 'reels' else kind
                self.assertEqual(
                    embed['url'], f'https://www.instagram.com/{expected_kind}/abcDEF_123-/embed',
                )
                self.assertTrue(embed['vertical'])

    def test_short_urls_are_resolved_on_click(self):
        for url, platform in (
            ('https://vm.tiktok.com/ZM8abcDEF/', 'tiktok'),
            ('https://www.tiktok.com/t/ZT8abcDEF/', 'tiktok'),
            ('https://instagr.am/p/abcDEF_123-/', 'instagram'),
        ):
            with self.subTest(url=url):
                embed = get_video_embed(url, 42)
                self.assertEqual(embed['url'], '/media/embed/42')
                self.assertEqual(embed['platform'], platform)
                self.assertTrue(embed['resolve'])

    def test_unsupported_and_lookalike_urls_do_not_embed(self):
        for url in (
            'https://youtube.com.evil.example/watch?v=dQw4w9WgXcQ',
            'https://www.youtube.com/watch?v=short',
            'https://www.tiktok.com/@user/video/123',
            'https://www.instagram.com/accounts/login/',
            'javascript:https://youtu.be/dQw4w9WgXcQ',
            'https://example.com/dQw4w9WgXcQ',
        ):
            with self.subTest(url=url):
                self.assertIsNone(get_video_embed(url, 42))


class VideoEmbedResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_tiktok_short_url(self):
        short_url = 'https://vm.tiktok.com/ZM8abcDEF/'
        response = httpx.Response(
            302,
            headers={
                'location': 'https://www.tiktok.com/@scout2015/video/6718335390845095173?is_from_webapp=1',
            },
        )
        with patch('web.video_embeds.httpx.AsyncClient') as client_class:
            client = client_class.return_value.__aenter__.return_value
            client.stream = MagicMock()
            client.stream.return_value.__aenter__.return_value = response

            embed = await resolve_video_embed(short_url)

        self.assertEqual(embed['url'], 'https://www.tiktok.com/player/v1/6718335390845095173?autoplay=1')
        client.stream.assert_called_once_with('GET', short_url)

    async def test_rejects_redirect_to_unsupported_host(self):
        response = httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
        with patch('web.video_embeds.httpx.AsyncClient') as client_class:
            client = client_class.return_value.__aenter__.return_value
            client.stream = MagicMock()
            client.stream.return_value.__aenter__.return_value = response

            embed = await resolve_video_embed('https://vm.tiktok.com/ZM8abcDEF/')

        self.assertIsNone(embed)
        client.stream.assert_called_once()
