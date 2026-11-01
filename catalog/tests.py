import re

from django.conf import settings
from django.test import TestCase


class ChannelPageTests(TestCase):
    def test_home_lists_channel_videos(self):
        response = self.client.get("/")
        body = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "The Machine Learning Engineer")
        self.assertIn("/video/", body)
        self.assertNotIn(settings.YOUTUBE_API_KEY, body)

        video_id = re.search(r"/video/([A-Za-z0-9_-]+)/", body).group(1)
        detail = self.client.get(f"/video/{video_id}/")
        detail_body = detail.content.decode()

        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Watch on YouTube")
        self.assertContains(detail, "Video id")
        self.assertContains(detail, "Views")
        self.assertNotIn(settings.YOUTUBE_API_KEY, detail_body)

    def test_find_page_ranks_a_description_and_opens_metadata(self):
        page = self.client.get("/find/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Find a video")

        found = self.client.get("/find/", {"q": "claude code agents installation"})
        body = found.content.decode()
        self.assertEqual(found.status_code, 200)
        self.assertContains(found, "Most similar")
        video_id = re.search(r"/video/([A-Za-z0-9_-]+)/", body).group(1)

        detail = self.client.get(f"/video/{video_id}/", {"q": "claude code agents installation"})
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "Video id")
        self.assertContains(detail, "Back to similar videos")
        self.assertNotIn(settings.YOUTUBE_API_KEY, detail.content.decode())

    def test_video_outside_the_channel_is_hidden(self):
        response = self.client.get("/video/dQw4w9WgXcQ/")
        self.assertEqual(response.status_code, 404)


# --- sync_youtube: no network, a fake client shaped like googleapiclient ------------

from datetime import date  # noqa: E402

from django.core.management import call_command  # noqa: E402

from catalog.models import (  # noqa: E402
    Channel,
    ChannelSnapshot,
    Playlist,
    PlaylistItem,
    Video,
    VideoStats,
)
from catalog.sync import duration_seconds, sync_channel  # noqa: E402

CHANNEL_ID = "UCtest000000000000000000"


class _Request:
    def __init__(self, response):
        self.response = response

    def execute(self):
        return self.response


class _Resource:
    def __init__(self, handler):
        self.handler = handler

    def list(self, **kwargs):
        return _Request(self.handler(**kwargs))


def _video(video_id, title, views, duration="PT10M5S", tags=None):
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "description": f"About {title}",
            "publishedAt": "2026-10-01T10:00:00Z",
            "channelId": CHANNEL_ID,
            "categoryId": "28",
            "tags": tags or [],
            "defaultAudioLanguage": "en",
            "thumbnails": {"medium": {"url": f"https://i.ytimg.com/vi/{video_id}/mq.jpg"}},
        },
        "contentDetails": {"duration": duration, "definition": "hd", "caption": "true", "licensedContent": False},
        "statistics": {"viewCount": str(views), "likeCount": "10", "commentCount": "2"},
        "status": {"privacyStatus": "public", "license": "youtube", "embeddable": True, "madeForKids": False},
        "topicDetails": {"topicCategories": ["https://en.wikipedia.org/wiki/Technology"]},
    }


class FakeYouTube:
    """Two pages of uploads (one hidden), one playlist. Views grow by `bump` per call."""

    def __init__(self, bump=0):
        self.videos_by_id = {
            "aaaaaaaaaaa": _video("aaaaaaaaaaa", "DuckDB intro", 100 + bump, tags=["duckdb", "sql"]),
            "bbbbbbbbbbb": _video("bbbbbbbbbbb", "MCP servers", 250 + bump, duration="PT1H2M3S"),
            "ccccccccccc": _video("ccccccccccc", "Claude Code", 40 + bump, duration="PT45S"),
        }

    def channels(self):
        return _Resource(
            lambda **kw: {
                "items": [
                    {
                        "id": CHANNEL_ID,
                        "snippet": {"title": "Test channel", "publishedAt": "2020-01-01T00:00:00Z"},
                        "statistics": {"subscriberCount": "1000", "viewCount": "390", "videoCount": "3"},
                        "contentDetails": {"relatedPlaylists": {"uploads": "UUuploads"}},
                    }
                ]
            }
        )

    def playlistItems(self):
        def handler(playlistId, pageToken=None, **kw):
            if playlistId == "UUuploads":
                if pageToken is None:
                    return {
                        "items": [
                            {"contentDetails": {"videoId": "aaaaaaaaaaa"}, "snippet": {"title": "DuckDB intro"}},
                            {"contentDetails": {"videoId": "zzzzzzzzzzz"}, "snippet": {"title": "Private video"}},
                        ],
                        "nextPageToken": "p2",
                    }
                return {
                    "items": [
                        {"contentDetails": {"videoId": "bbbbbbbbbbb"}, "snippet": {"title": "MCP servers"}},
                        {"contentDetails": {"videoId": "ccccccccccc"}, "snippet": {"title": "Claude Code"}},
                    ]
                }
            return {
                "items": [
                    {"contentDetails": {"videoId": "bbbbbbbbbbb"}, "snippet": {"title": "MCP servers", "position": 0}},
                    {"contentDetails": {"videoId": "aaaaaaaaaaa"}, "snippet": {"title": "DuckDB intro", "position": 1}},
                ]
            }

        return _Resource(handler)

    def videos(self):
        return _Resource(
            lambda id, **kw: {"items": [self.videos_by_id[v] for v in id.split(",") if v in self.videos_by_id]}
        )

    def playlists(self):
        return _Resource(
            lambda **kw: {
                "items": [
                    {
                        "id": "PLdata",
                        "snippet": {"title": "Data tools", "publishedAt": "2026-01-01T00:00:00Z"},
                        "contentDetails": {"itemCount": 2},
                        "status": {"privacyStatus": "public"},
                    }
                ]
            }
        )


class SyncTests(TestCase):
    def test_duration_seconds(self):
        self.assertEqual(duration_seconds("PT10M5S"), 605)
        self.assertEqual(duration_seconds("PT1H2M3S"), 3723)
        self.assertEqual(duration_seconds("P1DT1S"), 86401)
        self.assertEqual(duration_seconds(""), 0)
        self.assertEqual(duration_seconds("garbage"), 0)

    def test_sync_writes_channel_videos_stats_and_playlists(self):
        result = sync_channel(CHANNEL_ID, youtube=FakeYouTube(), today=date(2026, 11, 1))

        self.assertEqual(result.videos, 3)
        self.assertEqual(result.playlists, 1)
        self.assertEqual(result.playlist_items, 2)
        self.assertEqual(Channel.objects.get().uploads_playlist_id, "UUuploads")
        self.assertEqual(ChannelSnapshot.objects.get().subscriber_count, 1000)
        self.assertFalse(Video.objects.filter(id="zzzzzzzzzzz").exists())

        video = Video.objects.get(id="bbbbbbbbbbb")
        self.assertEqual(video.duration_seconds, 3723)
        self.assertEqual(video.category, "Science & Technology")
        self.assertTrue(video.caption)
        self.assertEqual(Video.objects.get(id="aaaaaaaaaaa").tags, ["duckdb", "sql"])
        self.assertEqual(VideoStats.objects.get(video_id="bbbbbbbbbbb").view_count, 250)
        self.assertEqual(
            list(PlaylistItem.objects.values_list("position", "video_id")),
            [(0, "bbbbbbbbbbb"), (1, "aaaaaaaaaaa")],
        )
        self.assertEqual(Playlist.objects.get().item_count, 2)

    def test_same_day_overwrites_and_next_day_adds_history(self):
        sync_channel(CHANNEL_ID, youtube=FakeYouTube(), today=date(2026, 11, 1))
        sync_channel(CHANNEL_ID, youtube=FakeYouTube(bump=5), today=date(2026, 11, 1))
        self.assertEqual(VideoStats.objects.count(), 3)
        self.assertEqual(VideoStats.objects.get(video_id="aaaaaaaaaaa").view_count, 105)

        sync_channel(CHANNEL_ID, youtube=FakeYouTube(bump=50), today=date(2026, 11, 2))
        self.assertEqual(VideoStats.objects.count(), 6)
        self.assertEqual(Video.objects.count(), 3)
        self.assertEqual(PlaylistItem.objects.count(), 2)

    def test_limit_and_no_playlists(self):
        result = sync_channel(CHANNEL_ID, youtube=FakeYouTube(), limit=2, playlists=False)
        self.assertEqual(result.videos, 2)
        self.assertEqual(Playlist.objects.count(), 0)

    def test_command_reports_a_missing_key(self):
        from django.core.management.base import CommandError
        from django.test import override_settings

        with override_settings(YOUTUBE_API_KEY=""):
            with self.assertRaisesMessage(CommandError, "YOUTUBE_API_KEY"):
                call_command("sync_youtube")
