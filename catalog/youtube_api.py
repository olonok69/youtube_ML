import math
import re
import unicodedata
from collections import Counter
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

PAGE_SIZE = 12
SIMILAR_LIMIT = 12
CHANNEL_CACHE_KEY = "youtube-channel-v1"
CATALOG_CACHE_KEY = "youtube-catalog-v1"
VIDEO_PARTS = "snippet,contentDetails,statistics,status,topicDetails"
VIDEO_ID_RE = re.compile(
    r"(?:v=|vi=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})"
)
STOPWORDS = frozenset(
    """
    a an the and or of to for in on with from by at as is are was were be this that
    these those it its you your we our they their not but if then than into over
    el la los las un una unos unas de del al y o en con por para que se su sus lo
    como más mas este esta estos estas ese esa eso video videos youtube http https
    www com
    """.split()
)
CATEGORIES = {
    "1": "Film & Animation",
    "2": "Autos & Vehicles",
    "10": "Music",
    "15": "Pets & Animals",
    "17": "Sports",
    "19": "Travel & Events",
    "20": "Gaming",
    "22": "People & Blogs",
    "23": "Comedy",
    "24": "Entertainment",
    "25": "News & Politics",
    "26": "Howto & Style",
    "27": "Education",
    "28": "Science & Technology",
    "29": "Nonprofits & Activism",
}


class YouTubeError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _client():
    api_key = settings.YOUTUBE_API_KEY
    if not api_key:
        raise YouTubeError("YOUTUBE_API_KEY is missing from keys/.env.")
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def _call(request):
    try:
        return request.execute()
    except HttpError as exc:
        status = getattr(exc.resp, "status", None)
        raise YouTubeError(
            f"YouTube API returned HTTP {status}. Check the key in keys/.env and that YouTube Data API v3 is enabled.",
            status=status,
        ) from exc


def _published(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _duration(value: str | None) -> str:
    if not value:
        return ""
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return value
    hours, minutes, seconds = (int(part) if part else 0 for part in match.groups())
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _thumbnail(thumbnails: dict | None) -> str:
    thumbnails = thumbnails or {}
    for size in ("medium", "high", "default"):
        url = thumbnails.get(size, {}).get("url")
        if url:
            return url
    return ""


def get_channel() -> dict:
    cached = cache.get(CHANNEL_CACHE_KEY)
    if cached:
        return cached

    response = _call(
        _client().channels().list(
            part="snippet,statistics,contentDetails",
            id=settings.YOUTUBE_CHANNEL_ID,
        )
    )
    items = response.get("items") or []
    if not items:
        raise YouTubeError(f"Channel not found: {settings.YOUTUBE_CHANNEL_ID}", status=404)

    item = items[0]
    snippet = item["snippet"]
    stats = item.get("statistics") or {}
    channel = {
        "id": item["id"],
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "custom_url": snippet.get("customUrl", ""),
        "thumbnail": _thumbnail(snippet.get("thumbnails")),
        "country": snippet.get("country", ""),
        "subscriber_count": int(stats.get("subscriberCount") or 0),
        "view_count": int(stats.get("viewCount") or 0),
        "video_count": int(stats.get("videoCount") or 0),
        "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
        "url": f"https://www.youtube.com/channel/{item['id']}",
    }
    cache.set(CHANNEL_CACHE_KEY, channel, 600)
    return channel


def _stats_by_id(video_ids: list[str]) -> dict[str, dict]:
    if not video_ids:
        return {}
    response = _call(
        _client().videos().list(
            part="statistics,contentDetails,snippet",
            id=",".join(video_ids),
        )
    )
    stats = {}
    for item in response.get("items") or []:
        counts = item.get("statistics") or {}
        stats[item["id"]] = {
            "view_count": int(counts.get("viewCount") or 0),
            "like_count": int(counts.get("likeCount") or 0),
            "comment_count": int(counts.get("commentCount") or 0),
            "duration": _duration(item.get("contentDetails", {}).get("duration")),
            "description": item.get("snippet", {}).get("description", ""),
            "channel_id": item.get("snippet", {}).get("channelId", ""),
        }
    return stats


def _video_card(video_id: str, snippet: dict, stats: dict) -> dict:
    return {
        "id": video_id,
        "title": snippet.get("title", ""),
        "description": stats.get("description") or snippet.get("description", ""),
        "published": _published(snippet.get("publishedAt")),
        "thumbnail": _thumbnail(snippet.get("thumbnails")),
        "view_count": stats.get("view_count", 0),
        "like_count": stats.get("like_count", 0),
        "comment_count": stats.get("comment_count", 0),
        "duration": stats.get("duration", ""),
        "url": f"https://www.youtube.com/watch?v={video_id}",
    }


def list_videos(page_token: str | None = None, query: str = "") -> dict:
    channel = get_channel()
    youtube = _client()
    query = query.strip()

    if query:
        response = _call(
            youtube.search().list(
                part="snippet",
                channelId=channel["id"],
                q=query,
                type="video",
                order="date",
                maxResults=PAGE_SIZE,
                pageToken=page_token or None,
            )
        )
        rows = []
        for item in response.get("items") or []:
            video_id = (item.get("id") or {}).get("videoId")
            if video_id:
                rows.append((video_id, item.get("snippet") or {}))
    else:
        response = _call(
            youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=channel["uploads_playlist_id"],
                maxResults=PAGE_SIZE,
                pageToken=page_token or None,
            )
        )
        rows = []
        for item in response.get("items") or []:
            video_id = (item.get("contentDetails") or {}).get("videoId")
            title = (item.get("snippet") or {}).get("title", "")
            if video_id and title not in {"Deleted video", "Private video"}:
                rows.append((video_id, item.get("snippet") or {}))

    details = _stats_by_id([video_id for video_id, _ in rows])
    videos = [
        _video_card(video_id, snippet, details.get(video_id, {}))
        for video_id, snippet in rows
    ]
    page_info = response.get("pageInfo") or {}
    return {
        "channel": channel,
        "videos": videos,
        "query": query,
        "next_page_token": response.get("nextPageToken") or "",
        "prev_page_token": response.get("prevPageToken") or "",
        "total_results": page_info.get("totalResults"),
    }


def _yes_no(value) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return ""


def _topic_name(url: str) -> str:
    name = url.rstrip("/").rsplit("/", 1)[-1].replace("_", " ")
    return name or url


def video_metadata_rows(video: dict) -> list[tuple[str, str]]:
    """Public fields worth showing on the video page, skipping blanks."""
    tags = ", ".join(video.get("tags") or [])
    topics = ", ".join(_topic_name(url) for url in video.get("topics") or [])
    pairs = [
        ("Video id", video.get("id", "")),
        ("Channel", video.get("channel_title", "")),
        ("Published", video["published"].strftime("%d %b %Y") if video.get("published") else ""),
        ("Duration", video.get("duration", "")),
        ("Views", f"{video.get('view_count', 0):,}"),
        ("Likes", f"{video.get('like_count', 0):,}"),
        ("Comments", f"{video.get('comment_count', 0):,}"),
        ("Category", video.get("category") or video.get("category_id", "")),
        ("Definition", (video.get("definition") or "").upper()),
        ("Dimension", video.get("dimension", "")),
        ("Projection", video.get("projection", "")),
        ("Captions", video.get("caption", "")),
        ("Language", video.get("language", "")),
        ("Audio language", video.get("audio_language", "")),
        ("Privacy", video.get("privacy_status", "")),
        ("License", video.get("license", "")),
        ("Embeddable", _yes_no(video.get("embeddable"))),
        ("Made for kids", _yes_no(video.get("made_for_kids"))),
        ("Licensed content", _yes_no(video.get("licensed_content"))),
        ("Tags", tags),
        ("Topics", topics),
        ("URL", video.get("url", "")),
    ]
    return [(label, value) for label, value in pairs if str(value).strip()]


def _video_record(item: dict) -> dict:
    snippet = item.get("snippet") or {}
    content = item.get("contentDetails") or {}
    counts = item.get("statistics") or {}
    status = item.get("status") or {}
    category_id = snippet.get("categoryId") or ""
    return {
        "id": item["id"],
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "published": _published(snippet.get("publishedAt")),
        "thumbnail": _thumbnail(snippet.get("thumbnails")),
        "channel_id": snippet.get("channelId", ""),
        "channel_title": snippet.get("channelTitle", ""),
        "tags": snippet.get("tags") or [],
        "category_id": category_id,
        "category": CATEGORIES.get(category_id, ""),
        "language": snippet.get("defaultLanguage") or "",
        "audio_language": snippet.get("defaultAudioLanguage") or "",
        "duration": _duration(content.get("duration")),
        "definition": content.get("definition") or "",
        "dimension": content.get("dimension") or "",
        "projection": content.get("projection") or "",
        "caption": content.get("caption") or "",
        "licensed_content": content.get("licensedContent"),
        "view_count": int(counts.get("viewCount") or 0),
        "like_count": int(counts.get("likeCount") or 0),
        "comment_count": int(counts.get("commentCount") or 0),
        "privacy_status": status.get("privacyStatus") or "",
        "license": status.get("license") or "",
        "embeddable": status.get("embeddable"),
        "made_for_kids": status.get("madeForKids"),
        "topics": (item.get("topicDetails") or {}).get("topicCategories") or [],
        "url": f"https://www.youtube.com/watch?v={item['id']}",
    }


def _records_by_id(video_ids: list[str]) -> dict[str, dict]:
    if not video_ids:
        return {}
    response = _call(
        _client().videos().list(part=VIDEO_PARTS, id=",".join(video_ids))
    )
    return {
        item["id"]: _video_record(item)
        for item in response.get("items") or []
    }


def lookup_video(video_id: str) -> dict | None:
    return _records_by_id([video_id]).get(video_id)


def get_video(video_id: str) -> dict:
    video = lookup_video(video_id)
    if video is None:
        raise YouTubeError("Video not found.", status=404)
    if video["channel_id"] != settings.YOUTUBE_CHANNEL_ID:
        raise YouTubeError("That video is not on this channel.", status=404)
    return video


def extract_video_id(value: str) -> str | None:
    """A pasted link or a bare id. A long description that mentions a URL stays text."""
    text = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", text):
        return text
    if len(text) > 180:
        return None
    match = VIDEO_ID_RE.search(text)
    return match.group(1) if match else None


def _tokens(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", text or "")
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    words = re.findall(r"[a-z0-9]{3,}", folded.lower())
    return [word for word in words if word not in STOPWORDS]


def channel_catalog() -> list[dict]:
    """Titles and descriptions for every public upload, cached for half an hour."""
    cached = cache.get(CATALOG_CACHE_KEY)
    if cached:
        return cached

    channel = get_channel()
    youtube = _client()
    videos = []
    page = None
    while True:
        response = _call(
            youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=channel["uploads_playlist_id"],
                maxResults=50,
                pageToken=page,
            )
        )
        for item in response.get("items") or []:
            video_id = (item.get("contentDetails") or {}).get("videoId")
            snippet = item.get("snippet") or {}
            title = snippet.get("title", "")
            if not video_id or title in {"Deleted video", "Private video"}:
                continue
            videos.append(
                {
                    "id": video_id,
                    "title": title,
                    "description": snippet.get("description", ""),
                    "published": _published(snippet.get("publishedAt")),
                    "thumbnail": _thumbnail(snippet.get("thumbnails")),
                    "channel_id": channel["id"],
                    "channel_title": channel["title"],
                    "view_count": 0,
                    "duration": "",
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                }
            )
        page = response.get("nextPageToken")
        if not page:
            break
    cache.set(CATALOG_CACHE_KEY, videos, 1800)
    return videos


def _similarity(query_tokens: list[str], document: str) -> float:
    if not query_tokens:
        return 0.0
    doc_tokens = _tokens(document)
    if not doc_tokens:
        return 0.0
    query = Counter(query_tokens)
    doc = Counter(doc_tokens)
    dot = sum(query[token] * doc[token] for token in query)
    query_norm = math.sqrt(sum(count * count for count in query.values()))
    doc_norm = math.sqrt(sum(count * count for count in doc.values()))
    if not query_norm or not doc_norm:
        return 0.0
    return dot / (query_norm * doc_norm)


def find_similar(raw: str) -> dict:
    """Rank channel videos against a pasted link or a description."""
    text = (raw or "").strip()
    video_id = extract_video_id(text)
    seed = lookup_video(video_id) if video_id else None
    if video_id and seed is None:
        raise YouTubeError("YouTube did not return that video.", status=404)

    compared = f"{seed['title']}\n{seed['description']}" if seed else text
    query_tokens = _tokens(compared)
    if not query_tokens:
        return {"query": text, "seed": seed, "matches": []}

    matches = []
    for video in channel_catalog():
        if seed and video["id"] == seed["id"]:
            continue
        score = _similarity(query_tokens, f"{video['title']}\n{video['description']}")
        if score <= 0:
            continue
        matches.append({"video": video, "score": round(score * 100)})
    matches.sort(key=lambda item: item["score"], reverse=True)
    top = matches[:SIMILAR_LIMIT]
    records = _records_by_id([item["video"]["id"] for item in top])
    for item in top:
        full = records.get(item["video"]["id"])
        if full:
            item["video"] = full
    return {"query": text, "seed": seed, "matches": top}
