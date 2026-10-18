#!/usr/bin/env python
"""Catalog the YouTube videos whose code lives in LLM_Notebooks.

This script does not read or write the only_readmes tree. It has its own
classes, log, and CSV files. The shared command in ``sync_channel.py`` can
call :class:`LlmNotebookSync` and, after that, put these CSVs into
``only_readmes/data/links.xlsx``. Running this file directly never does that.

YouTube is read-only. A video is included when its description links to
``olonok69/LLM_Notebooks``. The README column is the file path inside
``D:\\repos\\LLM_Notebooks``, not a copy stored anywhere else.

Outputs
-------

* ``llm_notebooks_catalog/links_english.csv``
* ``llm_notebooks_catalog/links_spanish.csv``
* ``logs/llm_notebooks_sync.log``

Run it on its own:

    uv run python llm_notebooks_sync.py
    uv run python llm_notebooks_sync.py --apply
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import unicodedata
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CHANNEL_ID = "UCqAi1lTsd2wj7p05-Oos4ug"
WORKSPACE = Path(__file__).resolve().parent
ENV_FILE = WORKSPACE / "keys" / ".env"
OUTPUT_DIR = WORKSPACE / "llm_notebooks_catalog"
EN_CSV = OUTPUT_DIR / "links_english.csv"
ES_CSV = OUTPUT_DIR / "links_spanish.csv"
LOG_FILE = WORKSPACE / "logs" / "llm_notebooks_sync.log"
REPO_ROOT = Path(r"D:\repos\LLM_Notebooks")
REPO_URL = "https://github.com/olonok69/LLM_Notebooks"

GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/[^\s)\]>'\"]+", re.I)
SHORT_RE = re.compile(r"#\s*shorts\b", re.I)
LLM_PATH_RE = re.compile(
    r"github\.com/olonok69/LLM_Notebooks(?:/(?:blob|tree|raw)/[^/]+/(.+))?",
    re.I,
)

log = logging.getLogger("llm_notebooks")


@dataclass
class LlmVideo:
    video_id: str
    title: str
    description: str
    published: datetime | None
    language: str
    views: int
    repo_path: str

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.video_id}"


@dataclass
class LlmCatalog:
    language: str
    path: Path
    category: str
    project: str
    description: str
    video: str
    rows: list[dict[str, str]] = field(default_factory=list)

    @property
    def columns(self) -> list[str]:
        return [
            self.category,
            self.project,
            self.description,
            self.video,
            "Observation",
            "Github",
            "Readme",
        ]


class LlmNotebookSync:
    """Build the English and Spanish CSVs for the LLM_Notebooks videos."""

    def run(self, apply: bool, exclude_ids: set[str] | None = None) -> list[LlmCatalog]:
        configure_logging()
        load_env(ENV_FILE)
        excluded = exclude_ids or set()
        log.info("Mode %s. YouTube is read-only.", "APPLY" if apply else "DRY RUN")
        log.info("Repository %s", REPO_ROOT)
        if excluded:
            log.info("Leaving %s videos in the other catalog", len(excluded))

        service = build(
            "youtube",
            "v3",
            developerKey=os.environ.get("YOUTUBE_API_KEY", ""),
            cache_discovery=False,
        )
        try:
            videos = collect_videos(service)
        except HttpError as exc:
            raise RuntimeError(f"YouTube API returned HTTP {exc.resp.status}") from exc

        english = LlmCatalog("en", EN_CSV, "Category", "Project", "Description", "video")
        spanish = LlmCatalog("es", ES_CSV, "Categoría", "Proyecto", "Descripción", "Video")
        for video in videos:
            if video.video_id in excluded:
                log.info("Skip %s because it is already in the channel catalog", video.video_id)
                continue
            catalog = spanish if video.language == "es" else english
            catalog.rows.append(make_row(catalog, video))
            log.info(
                "%s %s %s | %s",
                catalog.language,
                video.video_id,
                video.repo_path or "(repo root)",
                video.title,
            )

        for catalog in (english, spanish):
            log.info("%s rows prepared: %s", catalog.language, len(catalog.rows))
            if apply:
                write_catalog(catalog)
        if not apply:
            log.info("DRY RUN finished. Re-run with --apply to write the LLM Notebooks CSVs.")
        return [english, spanish]

    def build_playlist_pages(self) -> None:
        """Write playlist pages into the LLM_Notebooks repository.

        Videos and notebooks in this repository are public. Shorts playlists
        are omitted. This method does not read the only_readmes tree.
        """
        configure_logging()
        load_env(ENV_FILE)
        service = build(
            "youtube",
            "v3",
            developerKey=os.environ.get("YOUTUBE_API_KEY", ""),
            cache_discovery=False,
        )
        playlists = fetch_topic_playlists(service)
        rows_for = {
            "en": load_csv_rows(EN_CSV, "video", "Project", "Description"),
            "es": load_csv_rows(ES_CSV, "Video", "Proyecto", "Descripción"),
        }
        page_dir = REPO_ROOT / "playlists"
        page_dir.mkdir(parents=True, exist_ok=True)
        for old in page_dir.glob("*.md"):
            old.unlink()

        used_slugs: set[str] = set()
        covered = {"en": set(), "es": set()}
        grouped = {
            "en": {"Courses": [], "Playlists": []},
            "es": {"Courses in Spanish": [], "Playlists in Spanish": []},
        }
        for playlist in playlists:
            language = playlist["language"]
            selected = [
                rows_for[language][video_id]
                for video_id in playlist["video_ids"]
                if video_id in rows_for[language]
            ]
            if not selected:
                continue
            for video_id in playlist["video_ids"]:
                if video_id in rows_for[language]:
                    covered[language].add(video_id)
            slug = slugify(playlist["title"])
            if slug in used_slugs:
                slug = f"{slug}-{playlist['id'][-6:].lower()}"
            used_slugs.add(slug)
            page_name = f"{slug}.md"
            (page_dir / page_name).write_text(
                render_llm_detail(playlist["title"], playlist["id"], selected, language),
                encoding="utf-8",
            )
            if language == "es":
                section = "Courses in Spanish" if playlist["course"] else "Playlists in Spanish"
            else:
                section = "Courses" if playlist["course"] else "Playlists"
            grouped[language][section].append(
                {
                    "title": playlist["title"],
                    "page": f"playlists/{page_name}",
                    "count": len(selected),
                    "id": playlist["id"],
                }
            )
            log.info("Wrote %s (%s videos)", page_name, len(selected))

        extras = (
            ("en", "Playlists", "Other videos", "other-videos.md"),
            ("es", "Playlists in Spanish", "Otros videos", "otros-videos.md"),
        )
        for language, section, title, page_name in extras:
            missing = [row for video_id, row in rows_for[language].items() if video_id not in covered[language]]
            if not missing:
                continue
            (page_dir / page_name).write_text(
                render_llm_detail(title, "", missing, language),
                encoding="utf-8",
            )
            grouped[language][section].append(
                {"title": title, "page": f"playlists/{page_name}", "count": len(missing), "id": ""}
            )

        sections = []
        for heading, items in (
            ("Courses", grouped["en"]["Courses"]),
            ("Playlists", grouped["en"]["Playlists"]),
            ("Courses in Spanish", grouped["es"]["Courses in Spanish"]),
            ("Playlists in Spanish", grouped["es"]["Playlists in Spanish"]),
        ):
            if not items:
                continue
            lines = [f"## {heading}", ""]
            for item in sorted(items, key=lambda entry: entry["title"].lower()):
                youtube = (
                    f" [YouTube](https://www.youtube.com/playlist?list={item['id']})"
                    if item["id"]
                    else ""
                )
                count = item["count"]
                label = "video" if count == 1 else "videos"
                lines.append(
                    f"- [{item['title']}]({item['page']}) — {count} {label}.{youtube}"
                )
            sections.append("\n".join(lines))
        write_llm_readme("\n\n".join(sections) + "\n")
        log.info("Wrote playlist pages in %s", REPO_ROOT)



def configure_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("llm_notebooks")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    logger.info("Log file: %s", LOG_FILE)


def load_env(path: Path) -> None:
    """Load keys/.env. Values in the file replace a stale shell token."""
    if not path.exists():
        raise FileNotFoundError(f"Missing credential file: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key in {"GH_TOKEN", "YOUTUBE_API_KEY"}:
            os.environ[key] = value
        else:
            os.environ.setdefault(key, value)
    if not os.environ.get("YOUTUBE_API_KEY"):
        raise RuntimeError("YOUTUBE_API_KEY is missing from keys/.env")


def repo_path_from_description(description: str) -> str | None:
    """Return the path inside LLM_Notebooks, or an empty string for the repo root."""
    for match in GITHUB_URL_RE.findall(description or ""):
        found = LLM_PATH_RE.search(match.rstrip(".,);"))
        if not found:
            continue
        path = found.group(1) or ""
        path = re.split(r"https?://", path, maxsplit=1)[0]
        return urllib.parse.unquote(path.strip("/"))
    if "llm_notebooks" in (description or "").lower():
        return ""
    return None


def detect_language(snippet: dict) -> str:
    language = (
        snippet.get("defaultAudioLanguage") or snippet.get("defaultLanguage") or ""
    ).lower()
    if language.startswith("es"):
        return "es"
    if language.startswith("en"):
        return "en"
    text = f"{snippet.get('title') or ''} {snippet.get('description') or ''}"
    if re.search(r"[¿¡]|\b(introducción|cómo|para|con una|herramienta)\b", text, re.I):
        return "es"
    return "en"


def category_from_path(repo_path: str) -> str:
    if not repo_path:
        return "LLM Notebooks"
    first = repo_path.split("/", 1)[0].replace("_", " ").strip()
    return first or "LLM Notebooks"


def first_paragraph(description: str) -> str:
    paragraph: list[str] = []
    for line in (description or "").splitlines():
        stripped = line.strip()
        if not stripped:
            if paragraph:
                break
            continue
        if stripped.lower().startswith("http"):
            continue
        paragraph.append(stripped)
    return re.sub(r"\s+", " ", " ".join(paragraph)).strip()[:500]


def clean_title(title: str) -> str:
    text = re.sub(r"\s+#\S+", "", title or "")
    return re.sub(r"\s+", " ", text).strip()[:180]


def collect_videos(service) -> list[LlmVideo]:
    channel = service.channels().list(part="contentDetails", id=CHANNEL_ID).execute()
    items = channel.get("items") or []
    if not items:
        raise RuntimeError(f"Channel not found: {CHANNEL_ID}")
    playlist_id = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    video_ids: list[str] = []
    page_token = None
    while True:
        response = (
            service.playlistItems()
            .list(
                part="contentDetails,snippet",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )
        for item in response.get("items") or []:
            video_id = (item.get("contentDetails") or {}).get("videoId")
            title = (item.get("snippet") or {}).get("title", "")
            if video_id and title not in {"Private video", "Deleted video"}:
                video_ids.append(video_id)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    log.info("Channel uploads: %s", len(video_ids))

    selected: list[LlmVideo] = []
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        response = service.videos().list(part="snippet,statistics", id=",".join(batch)).execute()
        for item in response.get("items") or []:
            snippet = item.get("snippet") or {}
            description = snippet.get("description") or ""
            repo_path = repo_path_from_description(description)
            if repo_path is None:
                continue
            if SHORT_RE.search(snippet.get("title") or "") or SHORT_RE.search(description):
                log.info("Skip short %s | %s", item["id"], snippet.get("title") or "")
                continue
            published_raw = snippet.get("publishedAt")
            published = (
                datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                if published_raw
                else None
            )
            selected.append(
                LlmVideo(
                    video_id=item["id"],
                    title=snippet.get("title") or "",
                    description=description,
                    published=published,
                    language=detect_language(snippet),
                    views=int((item.get("statistics") or {}).get("viewCount") or 0),
                    repo_path=repo_path,
                )
            )
        log.info("Checked uploads %s-%s", start + 1, start + len(batch))
    selected.sort(key=lambda video: video.published.timestamp() if video.published else 0)
    log.info("Videos linked to LLM_Notebooks: %s", len(selected))
    return selected


def make_row(catalog: LlmCatalog, video: LlmVideo) -> dict[str, str]:
    local = REPO_ROOT / video.repo_path if video.repo_path else REPO_ROOT
    observation = "Cataloged from the LLM_Notebooks repository."
    if video.repo_path and not local.exists():
        observation += " The linked file was not found in D:\\repos\\LLM_Notebooks."
        log.warning("Missing local file for %s: %s", video.video_id, local)
    row = {column: "" for column in catalog.columns}
    row[catalog.category] = category_from_path(video.repo_path)
    row[catalog.project] = clean_title(video.title)
    row[catalog.description] = first_paragraph(video.description)
    row[catalog.video] = video.url
    row["Observation"] = observation
    row["Github"] = REPO_URL
    row["Readme"] = video.repo_path.replace("\\", "/")
    return row


def write_catalog(catalog: LlmCatalog) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with catalog.path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=catalog.columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in catalog.rows:
            writer.writerow({column: row.get(column, "") for column in catalog.columns})
    log.info("Wrote %s rows to %s", len(catalog.rows), catalog.path)


SPANISH_TITLE_RE = re.compile(r"español|espanol|inteligencia|finanzas|\bcurso\b", re.I)


def playlist_language(title: str) -> str:
    if SPANISH_TITLE_RE.search(title or ""):
        return "es"
    return "en"


def is_course_title(title: str) -> bool:
    lowered = title.lower()
    return "course" in lowered or "curso" in lowered


def slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text or "playlist")[:80]


def md_cell(value: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", value or "").strip().replace("|", "\\|")
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def video_id_from_url(value: str) -> str:
    match = re.search(r"(?:youtu\.be/|v=|shorts/)([A-Za-z0-9_-]{11})", value or "")
    return match.group(1) if match else ""


def quote_repo_path(path: str) -> str:
    return urllib.parse.quote(path.replace("\\", "/"), safe="/")


def course_playlist_ids(service) -> set[str]:
    """Playlists YouTube shows on the channel Courses shelves."""
    found: set[str] = set()
    response = (
        service.channelSections()
        .list(part="snippet,contentDetails", channelId=CHANNEL_ID)
        .execute()
    )
    for item in response.get("items") or []:
        title = ((item.get("snippet") or {}).get("title") or "").lower()
        if "course" not in title and "curso" not in title:
            continue
        found.update((item.get("contentDetails") or {}).get("playlists") or [])
    log.info("Course playlists on the channel: %s", len(found))
    return found


def fetch_topic_playlists(service) -> list[dict]:
    """Channel playlists except Shorts, with the video ids still on each list."""
    courses = course_playlist_ids(service)
    playlists = []
    page_token = None
    while True:
        response = (
            service.playlists()
            .list(
                part="snippet,contentDetails",
                channelId=CHANNEL_ID,
                maxResults=50,
                pageToken=page_token,
            )
            .execute()
        )
        for item in response.get("items") or []:
            title = item["snippet"]["title"]
            if "short" in title.lower():
                log.info("Skip shorts playlist %s", title)
                continue
            video_ids: list[str] = []
            titles: dict[str, str] = {}
            item_token = None
            while True:
                items = (
                    service.playlistItems()
                    .list(
                        part="snippet,contentDetails",
                        playlistId=item["id"],
                        maxResults=50,
                        pageToken=item_token,
                    )
                    .execute()
                )
                for entry in items.get("items") or []:
                    video_id = (entry.get("contentDetails") or {}).get("videoId")
                    snippet = entry.get("snippet") or {}
                    entry_title = snippet.get("title") or ""
                    if (
                        video_id
                        and entry_title not in {"Private video", "Deleted video"}
                        and not SHORT_RE.search(entry_title)
                        and not SHORT_RE.search(snippet.get("description") or "")
                    ):
                        video_ids.append(video_id)
                        titles[video_id] = entry_title
                item_token = items.get("nextPageToken")
                if not item_token:
                    break
            playlists.append(
                {
                    "id": item["id"],
                    "title": title,
                    "language": playlist_language(title),
                    "course": is_course_title(title) or item["id"] in courses,
                    "video_ids": video_ids,
                    "titles": titles,
                }
            )
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    log.info("Usable playlists: %s", len(playlists))
    return playlists


def load_csv_rows(path: Path, video_column: str, project_column: str, description_column: str) -> dict[str, dict[str, str]]:
    found = {}
    if not path.exists():
        return found
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            video_id = video_id_from_url(row.get(video_column, ""))
            if not video_id:
                continue
            if SHORT_RE.search(row.get(project_column, "") or "") or SHORT_RE.search(
                row.get(description_column, "") or ""
            ):
                continue
            found[video_id] = row
    return found


def render_llm_detail(title: str, playlist_id: str, rows: list[dict[str, str]], language: str) -> str:
    if language == "es":
        intro = "Los videos y los notebooks de esta lista son públicos."
        header = "| Tema | Proyecto | Descripción | Notebook | Video |"
        topic, project, description, video = "Categoría", "Proyecto", "Descripción", "Video"
    else:
        intro = "The videos and the notebooks on this list are public."
        header = "| Topic | Project | Description | Notebook | Video |"
        topic, project, description, video = "Category", "Project", "Description", "video"
    lines = [f"# {title}", "", intro, ""]
    if playlist_id:
        lines.extend([f"[YouTube playlist](https://www.youtube.com/playlist?list={playlist_id})", ""])
    lines.extend([header, "|------|---------|-------------|----------|-------|"])
    for row in rows:
        video_id = video_id_from_url(row.get(video, ""))
        readme = (row.get("Readme") or "").strip()
        notebook = f"[Notebook](../{quote_repo_path(readme)})" if readme else f"[Repository]({REPO_URL})"
        lines.append(
            "| {topic} | {project} | {description} | {notebook} | {watch} |".format(
                topic=md_cell(row.get(topic, ""), 60),
                project=md_cell(row.get(project, ""), 120),
                description=md_cell(row.get(description, ""), 180),
                notebook=notebook,
                watch=f"[▶️ Video](https://youtu.be/{video_id})" if video_id else "—",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


PLAYLIST_MARKER = "<!-- playlist-index -->"


def write_llm_readme(playlist_index: str) -> None:
    readme = REPO_ROOT / "README.md"
    original = readme.read_text(encoding="utf-8") if readme.exists() else "# LLM_Notebooks\n"
    if PLAYLIST_MARKER in original:
        head = original.split(PLAYLIST_MARKER)[0]
    elif "\n# Playlist\n" in original:
        head = original.split("\n# Playlist\n")[0]
    else:
        head = original.split("The videos and the notebooks in this repository are public.")[0]
    head = re.sub(r"\n#\s*$", "", head).rstrip()
    public_note = "The videos and the notebooks in this repository are public."
    while head.rstrip().endswith(public_note) or public_note in head.split("\n\n")[-1]:
        head = head[: head.rfind(public_note)].rstrip()
    note = (
        "\n\nThe videos and the notebooks in this repository are public. "
        "Shorts are not listed. Courses are lists. Open a list for the videos and the notebooks.\n\n"
        f"{PLAYLIST_MARKER}\n\n"
    )
    tail = "\n![alt text](image-2.png)\n" if (REPO_ROOT / "image-2.png").exists() else ""
    readme.write_text(head + note + playlist_index.rstrip() + "\n" + tail, encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Catalog YouTube videos for LLM_Notebooks.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write llm_notebooks_catalog CSVs. The default is a dry run.",
    )
    parser.add_argument(
        "--playlists",
        action="store_true",
        help="Rebuild the repository README as a playlist index and write one page per list.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        sync = LlmNotebookSync()
        if args.playlists:
            sync.build_playlist_pages()
            return 0
        sync.run(apply=args.apply)
    except Exception as exc:
        logging.basicConfig(level=logging.INFO)
        log.exception("LLM Notebooks sync failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
