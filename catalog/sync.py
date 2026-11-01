"""Copy the channel from the YouTube Data API into db.sqlite3.

Read-only on YouTube: every call is a list call with the API key. Each run upserts the
channel, its public uploads and its playlists, and writes one stats row per video for
today, so running it once a day builds a history of views, likes and comments.

Quota: about 1 unit per call. A channel with 200 uploads and 10 playlists costs
roughly 1 + 4 (uploads pages) + 4 (videos.list, 50 ids each) + 1 + 10 = 20 units.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Channel, ChannelSnapshot, Playlist, PlaylistItem, Video, VideoStats
from .youtube_api import CATEGORIES, VIDEO_PARTS, _call, _client, _published, _thumbnail

HIDDEN_TITLES = {"Deleted video", "Private video"}
DURATION_RE = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


@dataclass
class SyncResult:
    channel: str = ""
    videos: int = 0
    stats_rows: int = 0
    playlists: int = 0
    playlist_items: int = 0
    skipped: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.channel}: {self.videos} videos, {self.stats_rows} stats rows, "
            f"{self.playlists} playlists, {self.playlist_items} playlist items"
        )


def duration_seconds(value: str | None) -> int:
    """ISO 8601 duration from contentDetails (PT1H2M3S, P1DT2H) to seconds."""
    if not value:
        return 0
    match = DURATION_RE.fullmatch(value)
    if not match:
        return 0
    days, hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def _pages(request_for_page):
    """Yield every item of a paged list call."""
    token = None
    while True:
        response = _call(request_for_page(token))
        yield from response.get("items") or []
        token = response.get("nextPageToken")
        if not token:
            return


def _sync_channel(youtube, channel_id: str, today: date, now) -> Channel:
    response = _call(youtube.channels().list(part="snippet,statistics,contentDetails", id=channel_id))
    items = response.get("items") or []
    if not items:
        raise ValueError(f"Channel not found: {channel_id}")
    item = items[0]
    snippet = item.get("snippet") or {}
    stats = item.get("statistics") or {}
    channel, _ = Channel.objects.update_or_create(
        id=item["id"],
        defaults={
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "custom_url": snippet.get("customUrl", ""),
            "country": snippet.get("country", ""),
            "published": _published(snippet.get("publishedAt")),
            "thumbnail": _thumbnail(snippet.get("thumbnails")),
            "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
            "synced_at": now,
        },
    )
    ChannelSnapshot.objects.update_or_create(
        channel=channel,
        taken_on=today,
        defaults={
            "subscriber_count": int(stats.get("subscriberCount") or 0),
            "view_count": int(stats.get("viewCount") or 0),
            "video_count": int(stats.get("videoCount") or 0),
        },
    )
    return channel


def _upload_ids(youtube, channel: Channel, limit: int | None) -> list[str]:
    ids = []
    items = _pages(
        lambda token: youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=channel.uploads_playlist_id,
            maxResults=50,
            pageToken=token,
        )
    )
    for item in items:
        video_id = (item.get("contentDetails") or {}).get("videoId")
        title = (item.get("snippet") or {}).get("title", "")
        if video_id and title not in HIDDEN_TITLES:
            ids.append(video_id)
            if limit and len(ids) >= limit:
                break
    return ids


def _save_video(item: dict, channel: Channel, today: date, now) -> None:
    snippet = item.get("snippet") or {}
    content = item.get("contentDetails") or {}
    counts = item.get("statistics") or {}
    status = item.get("status") or {}
    category_id = snippet.get("categoryId") or ""
    video, _ = Video.objects.update_or_create(
        id=item["id"],
        defaults={
            "channel": channel,
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "published": _published(snippet.get("publishedAt")),
            "duration_seconds": duration_seconds(content.get("duration")),
            "category_id": category_id,
            "category": CATEGORIES.get(category_id, ""),
            "language": snippet.get("defaultLanguage") or "",
            "audio_language": snippet.get("defaultAudioLanguage") or "",
            "definition": content.get("definition") or "",
            "caption": content.get("caption") == "true",
            "licensed_content": content.get("licensedContent"),
            "privacy_status": status.get("privacyStatus") or "",
            "license": status.get("license") or "",
            "embeddable": status.get("embeddable"),
            "made_for_kids": status.get("madeForKids"),
            "thumbnail": _thumbnail(snippet.get("thumbnails")),
            "tags": snippet.get("tags") or [],
            "topics": (item.get("topicDetails") or {}).get("topicCategories") or [],
            "synced_at": now,
        },
    )
    VideoStats.objects.update_or_create(
        video=video,
        taken_on=today,
        defaults={
            "view_count": int(counts.get("viewCount") or 0),
            "like_count": int(counts.get("likeCount") or 0),
            "comment_count": int(counts.get("commentCount") or 0),
        },
    )


def _sync_playlists(youtube, channel: Channel, now, result: SyncResult) -> None:
    playlists = _pages(
        lambda token: youtube.playlists().list(
            part="snippet,contentDetails,status",
            channelId=channel.id,
            maxResults=50,
            pageToken=token,
        )
    )
    for item in playlists:
        snippet = item.get("snippet") or {}
        playlist, _ = Playlist.objects.update_or_create(
            id=item["id"],
            defaults={
                "channel": channel,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "published": _published(snippet.get("publishedAt")),
                "item_count": int((item.get("contentDetails") or {}).get("itemCount") or 0),
                "privacy_status": (item.get("status") or {}).get("privacyStatus") or "",
                "synced_at": now,
            },
        )
        result.playlists += 1
        rows = []
        entries = _pages(
            lambda token, playlist_id=playlist.id: youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=token,
            )
        )
        for entry in entries:
            entry_snippet = entry.get("snippet") or {}
            video_id = (entry.get("contentDetails") or {}).get("videoId")
            if not video_id or entry_snippet.get("title") in HIDDEN_TITLES:
                continue
            position = entry_snippet.get("position")
            rows.append(
                PlaylistItem(
                    playlist=playlist,
                    video_id=video_id,
                    position=len(rows) if position is None else int(position),
                    added=_published(entry_snippet.get("publishedAt")),
                )
            )
        # A playlist's order changes as a whole, so its items are replaced, not merged.
        playlist.items.all().delete()
        PlaylistItem.objects.bulk_create(rows)
        result.playlist_items += len(rows)


def sync_channel(
    channel_id: str | None = None,
    *,
    youtube=None,
    limit: int | None = None,
    playlists: bool = True,
    today: date | None = None,
) -> SyncResult:
    """Fetch the channel and write it to the database. `youtube` is injectable for tests."""
    youtube = youtube or _client()
    channel_id = channel_id or settings.YOUTUBE_CHANNEL_ID
    now = timezone.now()
    today = today or timezone.localdate()
    result = SyncResult()

    with transaction.atomic():
        channel = _sync_channel(youtube, channel_id, today, now)
        result.channel = channel.title
        ids = _upload_ids(youtube, channel, limit)
        for start in range(0, len(ids), 50):
            batch = ids[start : start + 50]
            response = _call(youtube.videos().list(part=VIDEO_PARTS, id=",".join(batch)))
            returned = set()
            for item in response.get("items") or []:
                _save_video(item, channel, today, now)
                returned.add(item["id"])
                result.videos += 1
                result.stats_rows += 1
            result.skipped.extend(video_id for video_id in batch if video_id not in returned)
        if playlists:
            _sync_playlists(youtube, channel, now, result)
    return result
