import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.youtube import (
    YouTubeClient, _classify_video_ids_sync, select_latest_by_kind,
)
from tests.postgres_support import TEST_POSTGRES_DSN, PostgresTestCase, queries


class YouTubeClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_latest_uploads(self):
        client = YouTubeClient('key', '@muuurrchik')
        client._get = AsyncMock(side_effect=[
            {
                'items': [{
                    'contentDetails': {'relatedPlaylists': {'uploads': 'uploads-id'}},
                }],
            },
            {
                'items': [{
                    'snippet': {
                        'resourceId': {'videoId': 'video-id'},
                        'title': 'Title',
                        'publishedAt': '2026-01-01T00:00:00Z',
                    },
                }],
            },
            {
                'items': [{
                    'snippet': {
                        'resourceId': {'videoId': 'video-id'},
                        'title': 'Title',
                        'publishedAt': '2026-01-01T00:00:00Z',
                    },
                }],
            },
        ])

        uploads = await client.fetch_latest_uploads()
        uploads_again = await client.fetch_latest_uploads()

        self.assertEqual(uploads[0]['video_id'], 'video-id')
        self.assertEqual(uploads_again[0]['title'], 'Title')
        self.assertEqual(client._get.await_count, 3)

    def test_select_latest_by_kind(self):
        uploads = [
            {'video_id': 'new-video'},
            {'video_id': 'short'},
            {'video_id': 'old-video'},
        ]
        classifications = {
            'new-video': 'video',
            'short': 'shorts',
            'old-video': 'video',
        }

        selected = select_latest_by_kind(uploads, classifications)

        self.assertEqual(selected['video']['video_id'], 'new-video')
        self.assertEqual(selected['shorts']['video_id'], 'short')

    def test_classification_uses_channel_tabs_and_filters_upcoming(self):
        with patch('services.youtube.yt_dlp.YoutubeDL') as youtube_dl:
            extractor = youtube_dl.return_value.__enter__.return_value
            extractor.extract_info.side_effect = [
                {'entries': [
                    {'id': 'video', 'live_status': 'not_live'},
                    {'id': 'upcoming', 'live_status': 'is_upcoming'},
                ]},
                {'entries': [{'id': 'short', 'live_status': 'not_live'}]},
            ]

            result = _classify_video_ids_sync(
                '@muuurrchik', ['video', 'short', 'upcoming'],
            )

        self.assertEqual(result, {'video': 'video', 'short': 'shorts'})


@unittest.skipUnless(TEST_POSTGRES_DSN, 'Требуется TEST_POSTGRES_DSN')
class YouTubeJobIntegrationTests(PostgresTestCase):
    async def test_publishes_latest_video_and_shorts_once(self):
        import handlers.youtube_job as job

        user = queries.ensure_user(100, 'user')
        for tag_name in ('muuurrchik', 'video', 'shorts'):
            tag = queries.create_tag(tag_name)
            queries.subscribe_tag(user['tg_id'], tag['id'])

        uploads = [
            {'video_id': 'new-video', 'title': 'New video', 'published_at': None},
            {'video_id': 'short', 'title': 'Short', 'published_at': None},
            {'video_id': 'old-video', 'title': 'Old video', 'published_at': None},
        ]
        classifications = {
            'new-video': 'video',
            'short': 'shorts',
            'old-video': 'video',
        }
        client = SimpleNamespace(fetch_latest_uploads=AsyncMock(return_value=uploads))
        config = SimpleNamespace(
            youtube_enabled=True,
            youtube_target_chat_id=200,
            youtube_channel_handle='@muuurrchik',
        )
        send_message = AsyncMock(side_effect=[
            SimpleNamespace(message_id=10),
            SimpleNamespace(message_id=11),
        ])
        context = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))

        with (
            patch.object(job, 'config', config),
            patch.object(job, 'youtube_client', client),
            patch.object(job, 'classify_video_ids', new=AsyncMock(return_value=classifications)),
            patch.object(job, 'mention_users', new=AsyncMock()) as mention_users,
        ):
            await job.check_youtube_channel(context)
            await job.check_youtube_channel(context)

        self.assertEqual(send_message.await_count, 2)
        texts = [call.kwargs['text'] for call in send_message.await_args_list]
        self.assertIn('https://www.youtube.com/watch?v=new-video\n#muuurrchik #video', texts)
        self.assertIn('https://www.youtube.com/shorts/short\n#muuurrchik #shorts', texts)
        self.assertNotIn('https://www.youtube.com/watch?v=old-video\n#muuurrchik #video', texts)
        self.assertEqual(mention_users.await_count, 2)
        self.assertEqual(queries.db('SELECT COUNT(*) AS cnt FROM youtube_publications').one()['cnt'], 2)
