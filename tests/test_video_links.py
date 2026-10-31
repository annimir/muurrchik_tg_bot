import unittest

from services.video_links import extract_video_tags


class VideoLinkTests(unittest.TestCase):
    def test_supported_platforms_with_hashtag(self):
        for url in (
            'https://youtu.be/video-id',
            'https://www.youtube.com/watch?v=video-id',
            'https://www.instagram.com/reel/video-id/',
            'https://www.tiktok.com/@user/video/123',
            'https://vm.tiktok.com/video-id/',
        ):
            with self.subTest(url=url):
                self.assertEqual(extract_video_tags(f'Смотрите {url} #videos'), ['videos'])

    def test_multiple_hashtags(self):
        self.assertEqual(
            extract_video_tags('https://youtu.be/video-id #first #second'),
            ['first', 'second'],
        )

    def test_link_or_hashtag_is_required(self):
        self.assertEqual(extract_video_tags('Текст без ссылки #videos'), [])
        self.assertEqual(extract_video_tags('https://youtu.be/video-id'), [])
        self.assertEqual(extract_video_tags('https://example.com/video #videos'), [])
