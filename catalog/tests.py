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
