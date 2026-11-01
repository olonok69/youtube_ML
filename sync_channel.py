#!/usr/bin/env python
"""Sync the YouTube channel into the only_readmes catalog.

YouTube is read-only. The script reads public video metadata and the
description you already published. It never uploads, edits, or deletes
anything on YouTube.

What it updates on disk, and only with ``--apply``:

* ``only_readmes/data/links_english.csv``
* ``only_readmes/data/links_spanish.csv``
* the README copy for each row, under the matching category folder
* ``only_readmes/Readme.md`` and ``only_readmes/Readme_es.md``

CSV columns
-----------

English: Category, Project, Description, video, Observation, Github, Readme
Spanish: Categoría, Proyecto, Descripción, Video, Observation, Github, Readme

``Readme`` is the path of that language's README relative to ``only_readmes``.
Empty Project, Description, video, and Github cells are filled from the video.
Category labels are normalized: ``Agentic IA`` becomes ``Agentic AI``, every
MCP label including Claude Desktop becomes ``MCP``, and ``Sin categoría``
becomes ``Time Series Forecasting``. ``Observation`` keeps existing text.

A video that is not in either CSV is a new catalog row when it was published
on or after the oldest video already in the CSVs. Older videos stay out of
this catalog. Videos whose description points at ``olonok69/LLM_Notebooks``
are written by ``llm_notebooks_sync.py`` into a separate catalog. ``--catalog
all`` runs both, then writes ``only_readmes/data/links.xlsx``.

The README file is downloaded from the GitHub link in the YouTube description.
If GitHub does not return the file, the same path is read from a local clone
under ``D:\\repos``, ``D:\\repos2``, ``D:\\repos3``, ``D:\\quantum``, or
``Z:\\repos``. Local video files are not consulted. YouTube is the source for
what was published.

The root pages keep the current table shape: category, project, description,
documentation link, and YouTube link in that language. The long overview under
the table is regenerated from the CSV so new topics stay visible.

Run it from this folder
-----------------------

Dry-run, the default. Calls YouTube and GitHub, writes only the log:

    uv run python sync_channel.py

Write the CSVs, README copies, and both root pages:

    uv run python sync_channel.py --apply

Try the first few catalog rows before a full write. ``--limit`` stays a dry run:

    uv run python sync_channel.py --catalog only-readmes
    uv run python sync_channel.py --apply --catalog all
    uv run python sync_channel.py --limit 5

The log is ``logs/sync_channel.log``. Django is installed in this uv
environment. Start the channel app from this folder with:

    uv run python manage.py runserver
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

CHANNEL_ID = "UCqAi1lTsd2wj7p05-Oos4ug"
WORKSPACE = Path(__file__).resolve().parent
ONLY_READMES = WORKSPACE / "only_readmes"
ENV_FILE = WORKSPACE / "keys" / ".env"
EN_CSV = ONLY_READMES / "data" / "links_english.csv"
ES_CSV = ONLY_READMES / "data" / "links_spanish.csv"
EN_INDEX = ONLY_READMES / "Readme.md"
ES_INDEX = ONLY_READMES / "Readme_es.md"
LOG_FILE = WORKSPACE / "logs" / "sync_channel.log"
BACKUP_DIR = WORKSPACE / "logs" / "backups"

LOCAL_REPO_ROOTS = (
    Path(r"D:\repos"),
    Path(r"D:\repos2"),
    Path(r"D:\repos3"),
    Path(r"D:\quantum"),
    Path(r"Z:\repos"),
)

NOTE_SUBSCRIBER = (
    "No public GitHub repository. The description says the notebook and code "
    "are for paying subscribers."
)
NOTE_MISSING_README = (
    "The description links to GitHub, but the README file could not be downloaded."
)
NOTE_ADDED = "Added from the YouTube channel. This video was not in the CSV."
NOTE_BOTH = "This video ID is also listed in the other language CSV."

# category label -> folder under only_readmes
CATEGORY_FOLDER = {
    "openai video processing": "OpenAI",
    "procesamiento de video openai": "OpenAI",
    "medical ai": "DICOM_FHIR",
    "ia médica": "DICOM_FHIR",
    "google ai": "Google_AI",
    "azure ai": "Azure",
    "azure multi-agent": "Azure",
    "azure multi-agente": "Azure",
    "nvidia gpu computing": "Nvidia",
    "distributed ocr": "Nats",
    "ocr distribuido": "Nats",
    "financial rag": "RAG",
    "rag financiero": "RAG",
    "trading strategy": "RAG",
    "trading analysis": "RAG",
    "estrategia trading": "RAG",
    "análisis trading": "RAG",
    "mortgage analysis": "RAG",
    "análisis hipotecario": "RAG",
    "neo4j rag": "RAG",
    "mcp client": "mcp",
    "cliente mcp": "mcp",
    "mcp platform": "mcp",
    "plataforma mcp": "mcp",
    "mcp tools": "mcp",
    "herramientas mcp": "mcp",
    "mcp search platform": "mcp",
    "plataforma búsqueda mcp": "mcp",
    "claude desktop": "mcp",
    "mcp development": "mcp",
    "desarrollo mcp": "mcp",
    "chatbot mcp": "mcp",
    "microsoft ai": "Microsoft_AI",
    "agentic ai": "Agentic_AI",
    "agentic ia": "Agentic_AI",
    "openapi / chatgpt": "OpenAI",
    "reinforcement learning": "Reinforcement_Learning",
    "mlops": "MLOPS",
    "computer vision": "Computer_Vision",
    "time series forecasting": "Time_Series_Forecasting",
    "uncategorized": "Time_Series_Forecasting",
    "sin categoría": "Time_Series_Forecasting",
    "sin categoria": "Time_Series_Forecasting",
    "mcp": "mcp",
}

# folder name -> (english category, spanish category, folder)
FOLDER_LABELS = {
    "openai": ("OpenAI Video Processing", "Procesamiento de Video OpenAI", "OpenAI"),
    "dicom_fhir": ("Medical AI", "IA Médica", "DICOM_FHIR"),
    "google_ai": ("Google AI", "Google AI", "Google_AI"),
    "azure": ("Azure AI", "Azure AI", "Azure"),
    "nvidia": ("NVIDIA GPU Computing", "NVIDIA GPU Computing", "Nvidia"),
    "nats": ("Distributed OCR", "OCR Distribuido", "Nats"),
    "rag": ("Financial RAG", "RAG Financiero", "RAG"),
    "mcp": ("MCP", "MCP", "mcp"),
    "microsoft_ai": ("Microsoft AI", "Microsoft AI", "Microsoft_AI"),
    "agentic_ai": ("Agentic AI", "Agentic AI", "Agentic_AI"),
    "reinforcement_learning": (
        "Reinforcement Learning",
        "Reinforcement Learning",
        "Reinforcement_Learning",
    ),
    "mlops": ("MLOPS", "MLOPS", "MLOPS"),
    "computer_vision": ("Computer Vision", "Computer Vision", "Computer_Vision"),
    "time_series_forecasting": (
        "Time Series Forecasting",
        "Time Series Forecasting",
        "Time_Series_Forecasting",
    ),
}

MCP_CATEGORY_LABELS = {
    "mcp",
    "mcp client",
    "mcp platform",
    "mcp tools",
    "mcp development",
    "mcp search platform",
    "claude desktop",
    "cliente mcp",
    "plataforma mcp",
    "herramientas mcp",
    "desarrollo mcp",
    "plataforma búsqueda mcp",
    "plataforma busqueda mcp",
    "chatbot mcp",
}
AGENTIC_CATEGORY_LABELS = {"agentic ai", "agentic ia", "aigentic ia", "agenti ai"}
UNCATEGORIZED_LABELS = {"sin categoría", "sin categoria", "uncategorized"}

# First matching group wins. Each item is (needles, en, es, folder).
CATEGORY_KEYWORDS: tuple[tuple[tuple[str, ...], str, str, str], ...] = (
    (("time series", "series temporales", "sktime", "timesfm"), "Time Series Forecasting", "Time Series Forecasting", "Time_Series_Forecasting"),
    (("super-resol", "super resol", "computer vision", "visión"), "Computer Vision", "Computer Vision", "Computer_Vision"),
    (("q-learning", "dqn", "rainbow", "reinforcement", " grpo", " ppo", "trpo"), "Reinforcement Learning", "Reinforcement Learning", "Reinforcement_Learning"),
    (("dicom", "presidio"), "Medical AI", "IA Médica", "DICOM_FHIR"),
    (("nats", "rapidocr"), "Distributed OCR", "OCR Distribuido", "Nats"),
    (("bollinger", "fibonacci", "donchian", "connors", "moving average", "medias móviles"), "Trading Strategy", "Estrategia Trading", "RAG"),
    (("copilot",), "Microsoft AI", "Microsoft AI", "Microsoft_AI"),
    (("foundry", "azure"), "Azure AI", "Azure AI", "Azure"),
    (("adk", "gemini", "bigquery"), "Google AI", "Google AI", "Google_AI"),
    (("mcp",), "MCP Tools", "Herramientas MCP", "mcp"),
    (("crewai", "agentic", "deep agent", "langgraph", "smolagent"), "Agentic AI", "Agentic AI", "Agentic_AI"),
    (("neo4j",), "Neo4j RAG", "Neo4j RAG", "RAG"),
    (("whisper", "video translat", "traductor de video"), "OpenAI Video Processing", "Procesamiento de Video OpenAI", "OpenAI"),
    (("mlops", " uv "), "MLOPS", "MLOPS", "MLOPS"),
)

EN_README_NAMES = ("README.md", "Readme.md", "readme.md", "Readme_en.md", "readme_en.md")
ES_README_NAMES = (
    "README_es.md",
    "Readme_es.md",
    "readme_es.md",
    "README.es.md",
    "README-es.md",
    "README_ES.md",
)

GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/[^\s)\]>'\"]+", re.I)
VIDEO_ID_RE = re.compile(r"(?:youtu\.be/|v=|shorts/)([A-Za-z0-9_-]{11})")
SUBSCRIBER_RE = re.compile(
    r"paying subscribers|paid subscribers|payd subscribers|subscriptores de pago|"
    r"solo para subscriptores",
    re.I,
)
SHORT_RE = re.compile(r"#\s*shorts\b", re.I)
TABLE_LINK_RE = re.compile(
    r"\[[^\]]+\]\(([^)]+)\)\s*\|\s*\[[^\]]+\]\(https?://youtu\.be/([A-Za-z0-9_-]{11})\)"
)

log = logging.getLogger("sync_channel")


@dataclass
class GithubRef:
    owner: str
    repo: str
    branch: str | None = None
    path: str | None = None
    url: str = ""

    @property
    def repo_url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}"


@dataclass
class Video:
    video_id: str
    title: str
    description: str
    published: datetime | None
    language: str
    views: int = 0
    refs: list[GithubRef] = field(default_factory=list)

    @property
    def url(self) -> str:
        return f"https://youtu.be/{self.video_id}"


@dataclass
class Catalog:
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


def load_env(path: Path) -> None:
    """Load keys/.env. The file wins over a GH_TOKEN already exported in the shell."""
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


def configure_logging() -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    log.info("Log file: %s", LOG_FILE)


def parse_github_url(url: str) -> GithubRef | None:
    cleaned = url.rstrip(".,);")
    match = re.match(
        r"https?://(?:www\.)?github\.com/([^/]+)/([^/#?]+)"
        r"(?:/(blob|tree|raw)/([^/]+)/(.+))?/?$",
        cleaned,
        re.I,
    )
    if not match:
        return None
    owner, repo, _kind, branch, path = match.groups()
    repo = repo.removesuffix(".git")
    if repo.lower() in {"blob", "tree", "issues", "pulls", "releases"}:
        return None
    return GithubRef(
        owner=owner,
        repo=repo,
        branch=branch,
        path=path.strip("/") if path else None,
        url=cleaned,
    )


def github_refs(description: str) -> list[GithubRef]:
    refs: list[GithubRef] = []
    seen: set[str] = set()
    for match in GITHUB_URL_RE.findall(description or ""):
        ref = parse_github_url(match)
        if ref is None or ref.repo_url.lower() in seen:
            continue
        seen.add(ref.repo_url.lower())
        refs.append(ref)
    refs.sort(key=lambda ref: ref.owner.lower() != "olonok69")
    return refs


def preferred_repo(refs: list[GithubRef]) -> GithubRef | None:
    for ref in refs:
        if ref.owner.lower() == "olonok69" and ref.repo.lower() != "llm_notebooks":
            return ref
    return refs[0] if refs else None


def is_llm_notebooks(video: Video) -> bool:
    if any(ref.repo.lower() == "llm_notebooks" for ref in video.refs):
        return True
    return "llm_notebooks" in (video.description or "").lower()


def is_subscriber_only(video: Video) -> bool:
    return not video.refs and bool(SUBSCRIBER_RE.search(video.description or ""))


def is_short_text(*parts: str) -> bool:
    return any(SHORT_RE.search(part or "") for part in parts)


def video_id_from_cell(value: str) -> str:
    match = VIDEO_ID_RE.search(value or "")
    if match:
        return match.group(1)
    bare = (value or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", bare):
        return bare
    return ""


def language_of_filename(name: str) -> str:
    lowered = name.lower()
    if re.search(r"(^|[._-])es([._-]|$)|español|spanish", lowered):
        return "es"
    return "en"


def add_note(row: dict[str, str], note: str) -> None:
    current = (row.get("Observation") or "").strip()
    if not note or note in current:
        return
    row["Observation"] = f"{current} | {note}" if current else note


def md_cell(value: str, limit: int = 280) -> str:
    text = re.sub(r"\s+", " ", value or "").strip().replace("|", "\\|")
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def quote_repo_path(path: str) -> str:
    return urllib.parse.quote(path.replace("\\", "/"), safe="/")


def safe_relative(path: str) -> Path:
    relative = Path(path.replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"Unsafe README path: {path}")
    return relative


def folder_for_category(category: str) -> str:
    return CATEGORY_FOLDER.get(category.strip().lower(), "Uncategorized")


def canonicalize_category(category: str, project: str) -> str:
    """Collapse the labels that must share one category."""
    label = (category or "").strip()
    key = label.lower()
    project_text = project or ""
    if key in UNCATEGORIZED_LABELS or "time series forecasting" in project_text.lower():
        return "Time Series Forecasting"
    if key in AGENTIC_CATEGORY_LABELS:
        return "Agentic AI"
    if key in MCP_CATEGORY_LABELS or re.search(r"\bMCP\b", project_text):
        return "MCP"
    return label


def is_markdown(path: str) -> bool:
    return Path(path).suffix.lower() in {".md", ".markdown"}


def infer_category(video: Video, ref: GithubRef | None) -> tuple[str, str, str]:
    """Return English label, Spanish label, and only_readmes folder."""
    if ref and ref.path:
        first = ref.path.split("/", 1)[0].lower()
        if first in FOLDER_LABELS:
            return FOLDER_LABELS[first]
    text = f" {video.title}\n{video.description} ".lower()
    for needles, english, spanish, folder in CATEGORY_KEYWORDS:
        if any(needle in text for needle in needles):
            return english, spanish, folder
    return "Uncategorized", "Sin categoría", "Uncategorized"


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
    text = re.sub(r"\s+", " ", " ".join(paragraph)).strip()
    return text[:500]


def detect_language(snippet: dict) -> str:
    """Use the audio language YouTube stored. Fall back to the title text."""
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


def clean_title(title: str) -> str:
    text = re.sub(r"\s+#\S+", "", title or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:180]


def load_catalog(catalog: Catalog) -> None:
    with catalog.path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            row = {key: (value or "").strip() for key, value in raw.items() if key}
            if not any(row.values()):
                continue
            row.setdefault("Readme", "")
            catalog.rows.append(row)
    log.info("%s rows loaded from %s", len(catalog.rows), catalog.path.name)


def index_existing_readmes(path: Path) -> dict[str, str]:
    """Map a YouTube id to the README path already published in a root index."""
    if not path.exists():
        return {}
    found: dict[str, str] = {}
    text = path.read_text(encoding="utf-8")
    for readme_path, video_id in TABLE_LINK_RE.findall(text):
        if readme_path.startswith("http"):
            continue
        found[video_id] = urllib.parse.unquote(readme_path)
    log.info("Indexed %s README paths from %s", len(found), path.name)
    return found


def youtube_service(api_key: str):
    if not api_key:
        raise RuntimeError("YOUTUBE_API_KEY is missing from keys/.env")
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def channel_uploads(service) -> tuple[str, str]:
    response = service.channels().list(part="snippet,contentDetails", id=CHANNEL_ID).execute()
    items = response.get("items") or []
    if not items:
        raise RuntimeError(f"Channel not found: {CHANNEL_ID}")
    item = items[0]
    playlist = item["contentDetails"]["relatedPlaylists"]["uploads"]
    title = item["snippet"]["title"]
    log.info("Channel %s uploads playlist %s", title, playlist)
    return title, playlist


def list_upload_ids(service, playlist_id: str) -> list[str]:
    ids: list[str] = []
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
                ids.append(video_id)
        page_token = response.get("nextPageToken")
        if not page_token:
            break
    log.info("Uploads playlist returned %s videos", len(ids))
    return ids


def fetch_videos(service, video_ids: list[str]) -> dict[str, Video]:
    videos: dict[str, Video] = {}
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        response = service.videos().list(
            part="snippet,statistics",
            id=",".join(batch),
        ).execute()
        for item in response.get("items") or []:
            snippet = item.get("snippet") or {}
            published_raw = snippet.get("publishedAt")
            published = (
                datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
                if published_raw
                else None
            )
            description = snippet.get("description") or ""
            videos[item["id"]] = Video(
                video_id=item["id"],
                title=snippet.get("title") or "",
                description=description,
                published=published,
                language=detect_language(snippet),
                views=int((item.get("statistics") or {}).get("viewCount") or 0),
                refs=github_refs(description),
            )
        log.info("Fetched video details %s-%s", start + 1, start + len(batch))
    return videos


def github_request(token: str, url: str, accept: str) -> bytes | None:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": accept,
            "User-Agent": "youtube-ml-sync",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        log.warning("GitHub HTTP %s for %s", exc.code, url.split("?")[0])
        return None
    except urllib.error.URLError as exc:
        log.warning("GitHub request failed for %s: %s", url.split("?")[0], exc.reason)
        return None


def list_github_dir(token: str, ref: GithubRef, directory: str) -> list[str]:
    branch = ref.branch or "main"
    quoted = quote_repo_path(directory)
    url = (
        f"https://api.github.com/repos/{ref.owner}/{ref.repo}/contents/{quoted}"
        f"?ref={urllib.parse.quote(branch)}"
    )
    payload = github_request(token, url, "application/vnd.github+json")
    if not payload:
        return []
    import json

    data = json.loads(payload.decode("utf-8"))
    if isinstance(data, dict):
        return []
    return [item.get("name", "") for item in data if item.get("type") == "file"]


def download_github_file(token: str, ref: GithubRef, path: str) -> str | None:
    branches = [ref.branch] if ref.branch else ["main", "master"]
    quoted = quote_repo_path(path)
    for branch in branches:
        url = (
            f"https://api.github.com/repos/{ref.owner}/{ref.repo}/contents/{quoted}"
            f"?ref={urllib.parse.quote(branch)}"
        )
        payload = github_request(token, url, "application/vnd.github.raw")
        if payload is not None:
            return payload.decode("utf-8", errors="replace")
    return None


def find_local_repo(repo_name: str) -> Path | None:
    for root in LOCAL_REPO_ROOTS:
        try:
            if not root.exists():
                log.info("Local repo root is not available: %s", root)
                continue
            direct = root / repo_name
            if direct.is_dir():
                return direct
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                nested = child / repo_name
                if nested.is_dir():
                    return nested
        except OSError as exc:
            log.warning("Could not read %s: %s", root, exc)
    return None


def read_local_file(repo_name: str, relative: str) -> str | None:
    repo = find_local_repo(repo_name)
    if repo is None:
        return None
    candidate = repo / relative
    if not candidate.is_file():
        return None
    log.info("Using local README %s", candidate)
    return candidate.read_text(encoding="utf-8", errors="replace")


def choose_filename(names: list[str], language: str) -> str | None:
    wanted = ES_README_NAMES if language == "es" else EN_README_NAMES
    lowered = {name.lower(): name for name in names}
    for candidate in wanted:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    for name in names:
        if name.lower().startswith("readme") and language_of_filename(name) == language:
            return name
    return None


def destination_for(category: str, ref: GithubRef, relative_file: str) -> Path:
    """Pick only_readmes/<category>/<project>/<file>, or keep a mirrored path."""
    parts = relative_file.split("/")
    if len(parts) >= 2 and parts[0].lower() in FOLDER_LABELS:
        return safe_relative(relative_file)
    folder = folder_for_category(category)
    filename = parts[-1]
    return safe_relative(f"{folder}/{ref.repo}/{filename}")


def resolve_readme(
    token: str,
    video: Video,
    language: str,
    category: str,
    indexed_path: str | None,
) -> tuple[str, str | None]:
    """Return the relative README path and its text, when the file can be read."""
    ref = preferred_repo(video.refs)
    if indexed_path:
        relative = safe_relative(indexed_path).as_posix()
        text = None
        if ref is not None:
            github_path = relative
            if ref.path and language_of_filename(Path(ref.path).name) == language:
                github_path = ref.path
            text = download_github_file(token, ref, github_path)
            if text is None and ref.path:
                text = read_local_file(ref.repo, ref.path)
            if text is None:
                text = read_local_file(ref.repo, relative)
        return relative, text

    if ref is None:
        return "", None

    directory = ""
    filename = ""
    if ref.path and is_markdown(ref.path):
        path = ref.path
        if language_of_filename(Path(path).name) != language:
            directory = str(Path(path).parent).replace("\\", "/")
            if directory == ".":
                directory = ""
            names = list_github_dir(token, ref, directory)
            filename = choose_filename(names, language) or ""
            path = f"{directory}/{filename}" if directory and filename else filename
        if path:
            text = download_github_file(token, ref, path)
            if text is None:
                text = read_local_file(ref.repo, path)
            dest = destination_for(category, ref, path)
            return dest.as_posix(), text

    names = list_github_dir(token, ref, "")
    filename = choose_filename(names, language) or (
        "README_es.md" if language == "es" else "README.md"
    )
    text = download_github_file(token, ref, filename)
    if text is None:
        text = read_local_file(ref.repo, filename)
    dest = destination_for(category, ref, filename)
    return dest.as_posix(), text


def blank(row: dict[str, str], column: str) -> bool:
    return not (row.get(column) or "").strip()


def fill_row(
    catalog: Catalog,
    row: dict[str, str],
    video: Video | None,
    token: str,
    indexed: dict[str, str],
    known_ids: set[str],
) -> str | None:
    """Fill empty cells and return README text that should be written."""
    video_id = video_id_from_cell(row.get(catalog.video, ""))
    if video is None:
        log.warning("No YouTube details for %s row %s", catalog.path.name, video_id or row)
        add_note(row, "YouTube did not return this video.")
        return None

    published = video.published.date().isoformat() if video.published else "unknown"
    log.info(
        "%s %s published %s views %s | %s",
        catalog.language,
        video.video_id,
        published,
        video.views,
        video.title,
    )
    if blank(row, catalog.video):
        row[catalog.video] = video.url
        log.info("Filled video URL for %s", video.video_id)
    if blank(row, catalog.project):
        row[catalog.project] = clean_title(video.title)
        log.info("Filled project for %s", video.video_id)
    if blank(row, catalog.description):
        row[catalog.description] = first_paragraph(video.description)
        log.info("Filled description for %s", video.video_id)

    english, spanish, _folder = infer_category(video, preferred_repo(video.refs))
    if blank(row, catalog.category):
        row[catalog.category] = spanish if catalog.language == "es" else english
        log.info("Filled category %s for %s", row[catalog.category], video.video_id)
    canonical = canonicalize_category(row.get(catalog.category, ""), row.get(catalog.project, ""))
    if canonical and canonical != row.get(catalog.category):
        log.info("Category %s -> %s for %s", row.get(catalog.category), canonical, video.video_id)
        row[catalog.category] = canonical
    readme_path = (row.get("Readme") or "").replace("\\", "/")
    if readme_path.startswith("Uncategorized/"):
        row["Readme"] = "Time_Series_Forecasting/" + readme_path.split("/", 1)[1]
        log.info("Moved README path to %s", row["Readme"])

    repo = preferred_repo(video.refs)
    if blank(row, "Github") and repo is not None:
        row["Github"] = repo.repo_url
        log.info("Filled GitHub %s for %s", repo.repo_url, video.video_id)
    elif video.refs and repo is None:
        row["Github"] = video.refs[0].repo_url

    if is_subscriber_only(video):
        add_note(row, NOTE_SUBSCRIBER)
        log.info("Subscriber-only video %s", video.video_id)
    if video.video_id in known_ids:
        add_note(row, NOTE_BOTH)

    indexed_path = indexed.get(video.video_id)
    if not video.refs and not indexed_path:
        row.setdefault("Readme", "")
        return None

    relative, text = resolve_readme(
        token,
        video,
        catalog.language,
        row.get(catalog.category, ""),
        indexed_path,
    )
    if relative and blank(row, "Readme"):
        row["Readme"] = relative
    elif row.get("Readme"):
        relative = row["Readme"]
    if text is None and relative and (ONLY_READMES / safe_relative(relative)).is_file():
        log.info("Keeping the README already stored at %s", relative)
        return None
    if video.refs and not text:
        add_note(row, NOTE_MISSING_README)
        log.warning("README missing for %s", video.video_id)
    return text if relative else None


def new_row(catalog: Catalog, video: Video) -> dict[str, str]:
    english, spanish, _folder = infer_category(video, preferred_repo(video.refs))
    repo = preferred_repo(video.refs)
    row = {column: "" for column in catalog.columns}
    row[catalog.project] = clean_title(video.title)
    row[catalog.category] = canonicalize_category(
        spanish if catalog.language == "es" else english,
        row[catalog.project],
    )
    row[catalog.description] = first_paragraph(video.description)
    row[catalog.video] = video.url
    row["Github"] = repo.repo_url if repo else ""
    row["Observation"] = NOTE_ADDED
    if is_subscriber_only(video):
        add_note(row, NOTE_SUBSCRIBER)
    return row


def write_csv(catalog: Catalog) -> None:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = BACKUP_DIR / f"{catalog.path.stem}-{stamp}.csv"
    backup.write_bytes(catalog.path.read_bytes())
    log.info("Backed up %s to %s", catalog.path.name, backup)
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


def write_readme_file(relative: str, text: str, apply: bool) -> None:
    if not is_markdown(relative):
        log.info("Skipping non-markdown file %s", relative)
        return
    destination = ONLY_READMES / safe_relative(relative)
    existing = destination.read_text(encoding="utf-8", errors="replace") if destination.exists() else None
    if existing is not None and existing.replace("\r\n", "\n") == text.replace("\r\n", "\n"):
        log.info("README unchanged %s", relative)
        return
    action = "Updating" if destination.exists() else "Creating"
    log.info("%s README %s (%s characters)", action, relative, len(text))
    if not apply:
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text.replace("\r\n", "\n"), encoding="utf-8")


def render_index(catalog: Catalog) -> str:
    if catalog.language == "es":
        title = "# Repositorio de IA & ML - Guía Completa"
        intro = (
            "Una colección de proyectos de IA y ML documentados junto con el video "
            "del canal en español. La tabla sale de `data/links_spanish.csv`."
        )
        heading = "## 📋 Tabla de Contenidos"
        header = "| Categoría | Proyecto | Descripción | Documentación | Video |"
        doc_label = "📖 Español"
        overview = "## Descripción del repositorio"
    else:
        title = "# AI & ML Repository - Comprehensive Guide"
        intro = (
            "A collection of AI and ML projects documented with the matching English "
            "video from the channel. The table is generated from `data/links_english.csv`."
        )
        heading = "## 📋 Table of Contents"
        header = "| Category | Project | Description | Documentation | Video |"
        doc_label = "📖 English"
        overview = "## Repository overview"

    lines = [
        title,
        "",
        intro,
        "",
        heading,
        "",
        header,
        "|----------|---------|-------------|-------------- |---|",
    ]
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in catalog.rows:
        category = row.get(catalog.category, "").strip() or "Uncategorized"
        grouped.setdefault(category, []).append(row)
        readme = (row.get("Readme") or "").strip()
        video_id = video_id_from_cell(row.get(catalog.video, ""))
        doc = f"[{doc_label}]({quote_repo_path(readme)})" if readme else "—"
        video = f"[▶️ Video](https://youtu.be/{video_id})" if video_id else "—"
        lines.append(
            "| **{category}** | {project} | {description} | {doc} | {video} |".format(
                category=md_cell(category, 80),
                project=md_cell(row.get(catalog.project, ""), 120),
                description=md_cell(row.get(catalog.description, "")),
                doc=doc,
                video=video,
            )
        )

    lines.extend(["", overview, ""])
    for category, rows in grouped.items():
        lines.append(f"### {category}")
        lines.append("")
        for row in rows:
            project = row.get(catalog.project, "").strip()
            description = re.sub(r"\s+", " ", row.get(catalog.description, "")).strip()
            if description:
                lines.append(f"- **{project}.** {description}")
            else:
                lines.append(f"- **{project}.**")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_index(path: Path, content: str, apply: bool) -> None:
    log.info("Prepared %s (%s characters)", path.name, len(content))
    if apply:
        path.write_text(content, encoding="utf-8")
        log.info("Wrote %s", path)


def catalog_video_ids(catalogs: list[Catalog]) -> set[str]:
    found: set[str] = set()
    for catalog in catalogs:
        for row in catalog.rows:
            video_id = video_id_from_cell(row.get(catalog.video, ""))
            if video_id:
                found.add(video_id)
    return found


def ids_in_both(catalogs: list[Catalog]) -> set[str]:
    per_language: list[set[str]] = []
    for catalog in catalogs:
        per_language.append(
            {
                video_id_from_cell(row.get(catalog.video, ""))
                for row in catalog.rows
                if video_id_from_cell(row.get(catalog.video, ""))
            }
        )
    return per_language[0] & per_language[1]


def process(apply: bool, limit: int | None) -> None:
    load_env(ENV_FILE)
    api_key = os.environ.get("YOUTUBE_API_KEY", "")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise RuntimeError("GH_TOKEN is missing from keys/.env")

    mode = "APPLY" if apply else "DRY RUN"
    log.info("Mode %s. YouTube is read-only.", mode)

    english = Catalog("en", EN_CSV, "Category", "Project", "Description", "video")
    spanish = Catalog("es", ES_CSV, "Categoría", "Proyecto", "Descripción", "Video")
    catalogs = [english, spanish]
    for catalog in catalogs:
        load_catalog(catalog)
    indexes = {
        "en": index_existing_readmes(EN_INDEX),
        "es": index_existing_readmes(ES_INDEX),
    }

    service = youtube_service(api_key)
    try:
        _title, playlist_id = channel_uploads(service)
        if limit is None:
            upload_ids = list_upload_ids(service, playlist_id)
            needed = list(dict.fromkeys([*catalog_video_ids(catalogs), *upload_ids]))
        else:
            upload_ids = []
            needed = []
            for catalog in catalogs:
                for row in catalog.rows[:limit]:
                    video_id = video_id_from_cell(row.get(catalog.video, ""))
                    if video_id:
                        needed.append(video_id)
            log.info("--limit %s checks existing CSV rows only", limit)
        videos = fetch_videos(service, needed)
    except HttpError as exc:
        raise RuntimeError(f"YouTube API returned HTTP {exc.resp.status}") from exc

    known_before = ids_in_both(catalogs)
    published_dates = [
        video.published
        for video_id, video in videos.items()
        if video_id in catalog_video_ids(catalogs) and video.published
    ]
    cutoff = min(published_dates) if published_dates else None
    if cutoff:
        log.info("Catalog window starts at %s. Older uploads stay in phase 2.", cutoff.date())

    pending_files: list[tuple[str, str]] = []

    for catalog in catalogs:
        rows = catalog.rows if limit is None else catalog.rows[:limit]
        for row in rows:
            video_id = video_id_from_cell(row.get(catalog.video, ""))
            text = fill_row(
                catalog,
                row,
                videos.get(video_id),
                token,
                indexes[catalog.language],
                known_before,
            )
            relative = (row.get("Readme") or "").strip()
            if text and relative:
                pending_files.append((relative, text))

    if limit is None:
        known_ids = catalog_video_ids(catalogs)
        for video_id in upload_ids:
            if video_id in known_ids:
                continue
            video = videos.get(video_id)
            if video is None:
                log.warning("Upload %s has no video details", video_id)
                continue
            if is_short_text(video.title, video.description):
                log.info("Skip short %s | %s", video.video_id, video.title)
                continue
            if is_llm_notebooks(video) or (cutoff and video.published and video.published < cutoff):
                log.info(
                    "PHASE2 skip %s published %s | %s",
                    video.video_id,
                    video.published.date().isoformat() if video.published else "unknown",
                    video.title,
                )
                continue
            catalog = spanish if video.language == "es" else english
            row = new_row(catalog, video)
            catalog.rows.append(row)
            known_ids.add(video_id)
            log.info("New %s CSV row for %s | %s", catalog.language, video.video_id, video.title)
            text_relative = resolve_readme(
                token,
                video,
                catalog.language,
                row.get(catalog.category, ""),
                None,
            )
            relative, text = text_relative
            if relative:
                row["Readme"] = relative
            if video.refs and not text:
                add_note(row, NOTE_MISSING_README)
            if text and relative:
                pending_files.append((relative, text))

    stray = ONLY_READMES / "Computer_Vision" / "LLM_Notebooks" / "Zoom_Resize_Image_extended.ipynb"
    if stray.is_file():
        log.info("Removing non-markdown copy %s", stray.relative_to(ONLY_READMES))
        if apply:
            stray.unlink()

    for catalog in catalogs:
        kept = []
        for row in catalog.rows:
            if is_short_text(row.get(catalog.project, ""), row.get(catalog.description, "")):
                log.info("Drop short from %s: %s", catalog.path.name, row.get(catalog.video, ""))
                continue
            kept.append(row)
        catalog.rows = kept

    for relative, text in pending_files:
        write_readme_file(relative, text, apply)

    write_index(EN_INDEX, render_index(english), apply)
    write_index(ES_INDEX, render_index(spanish), apply)
    if apply:
        write_csv(english)
        write_csv(spanish)
    else:
        log.info("DRY RUN finished. Re-run with --apply to write CSVs and READMEs.")
    log.info(
        "Done. English rows %s, Spanish rows %s, README files considered %s.",
        len(english.rows),
        len(spanish.rows),
        len(pending_files),
    )


def video_ids_in_catalog_csvs() -> set[str]:
    """IDs already kept in the only_readmes catalogs. Used only by this entry point."""
    found: set[str] = set()
    for path, column in ((EN_CSV, "video"), (ES_CSV, "Video")):
        if not path.exists():
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                video_id = video_id_from_cell(row.get(column, ""))
                if video_id:
                    found.add(video_id)
    return found


SPANISH_TITLE_RE = re.compile(r"español|espanol|inteligencia|finanzas|\bcurso\b", re.I)


def playlist_language(title: str) -> str:
    if SPANISH_TITLE_RE.search(title or ""):
        return "es"
    return "en"


def is_course_title(title: str) -> bool:
    lowered = title.lower()
    return "course" in lowered or "curso" in lowered


def is_shorts_playlist(title: str) -> bool:
    return "short" in title.lower()


def slugify(title: str) -> str:
    text = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()
    return (text or "playlist")[:80]


def row_is_subscriber(row: dict[str, str]) -> bool:
    text = (row.get("Observation") or "").lower()
    return "subscriber" in text or "suscriptor" in text


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


def fetch_channel_playlists(service) -> list[dict]:
    """Return non-short playlists with the video ids still on each list."""
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
            if is_shorts_playlist(title):
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
                        and not is_short_text(entry_title, snippet.get("description") or "")
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


def catalog_rows_by_id(catalog: Catalog) -> dict[str, dict[str, str]]:
    found = {}
    for row in catalog.rows:
        video_id = video_id_from_cell(row.get(catalog.video, ""))
        if video_id and not is_short_text(row.get(catalog.project, ""), row.get(catalog.description, "")):
            found[video_id] = row
    return found


def documentation_cell(row: dict[str, str], language: str, prefix: str = "") -> str:
    if row_is_subscriber(row):
        if language == "es":
            return "Video público. Código solo para suscriptores de pago."
        return "Public video. Code for paid subscribers."
    readme = (row.get("Readme") or "").strip()
    if not readme:
        return "—"
    label = "📖 Español" if language == "es" else "📖 English"
    return f"[{label}]({prefix}{quote_repo_path(readme)})"


def render_detail_page(title: str, playlist_id: str, rows: list[tuple[Catalog, dict[str, str]]], language: str) -> str:
    if language == "es":
        intro = (
            "Todos los videos de esta lista se pueden ver. "
            "Cuando el código es solo para suscriptores de pago, la tabla lo indica."
        )
        header = "| Categoría | Proyecto | Descripción | Documentación | Video |"
        doc_prefix = "../"
    else:
        intro = (
            "Every video on this list can be watched. "
            "When the code is for paid subscribers, the table says so."
        )
        header = "| Category | Project | Description | Documentation | Video |"
        doc_prefix = "../"
    lines = [
        f"# {title}",
        "",
        intro,
        "",
    ]
    if playlist_id:
        lines.extend([f"[YouTube playlist](https://www.youtube.com/playlist?list={playlist_id})", ""])
    lines.extend([
        header,
        "|----------|---------|-------------|-------------- |---|",
    ])
    for catalog, row in rows:
        video_id = video_id_from_cell(row.get(catalog.video, ""))
        lines.append(
            "| **{category}** | {project} | {description} | {doc} | {video} |".format(
                category=md_cell(row.get(catalog.category, ""), 80),
                project=md_cell(row.get(catalog.project, ""), 120),
                description=md_cell(row.get(catalog.description, ""), 180),
                doc=documentation_cell(row, language, doc_prefix),
                video=f"[▶️ Video](https://youtu.be/{video_id})" if video_id else "—",
            )
        )
    return "\n".join(lines).rstrip() + "\n"


def render_playlist_index(language: str, sections: list[tuple[str, list[dict]]]) -> str:
    if language == "es":
        title = "# Repositorio de IA y ML"
        intro = (
            "Los videos del canal son públicos. En algunos proyectos el código es solo "
            "para suscriptores de pago; la página de cada lista lo indica. "
            "Los Shorts no están incluidos. Los cursos se tratan como listas."
        )
        empty = "Esta sección todavía no tiene listas en el catálogo."
    else:
        title = "# AI & ML Repository"
        intro = (
            "Channel videos are public. For some projects the code is for paid subscribers; "
            "each list page says which ones. Shorts are not included. Courses are lists."
        )
        empty = "This section has no lists in the catalog yet."
    lines = [
        title,
        "",
        intro,
        "",
        "[The Machine Learning Engineer](https://www.youtube.com/channel/UCqAi1lTsd2wj7p05-Oos4ug)",
        "",
        "[Español](Readme_es.md)" if language == "en" else "[English](Readme.md)",
        "",
    ]
    for heading, items in sections:
        lines.extend([f"## {heading}", ""])
        if not items:
            lines.append(empty)
            lines.append("")
            continue
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
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_only_readmes_playlist_pages() -> None:
    """Write the playlist index and one detail page per list. YouTube stays read-only."""
    load_env(ENV_FILE)
    service = youtube_service(os.environ.get("YOUTUBE_API_KEY", ""))
    playlists = fetch_channel_playlists(service)
    english = Catalog("en", EN_CSV, "Category", "Project", "Description", "video")
    spanish = Catalog("es", ES_CSV, "Categoría", "Proyecto", "Descripción", "Video")
    load_catalog(english)
    load_catalog(spanish)
    rows_for = {
        "en": catalog_rows_by_id(english),
        "es": catalog_rows_by_id(spanish),
    }
    catalogs = {"en": english, "es": spanish}
    page_dir = ONLY_READMES / "playlists"
    page_dir.mkdir(parents=True, exist_ok=True)
    for old in page_dir.glob("*.md"):
        old.unlink()

    used_slugs: set[str] = set()
    covered = {"en": set(), "es": set()}
    grouped = {
        "en": {"Courses": [], "Playlists": []},
        "es": {"Cursos": [], "Listas": []},
    }
    for playlist in playlists:
        language = playlist["language"]
        selected = []
        for video_id in playlist["video_ids"]:
            row = rows_for[language].get(video_id)
            if row:
                selected.append((catalogs[language], row))
                covered[language].add(video_id)
        if not selected and playlist["course"]:
            catalog = catalogs[language]
            for video_id in playlist["video_ids"]:
                row = {column: "" for column in catalog.columns}
                row[catalog.category] = "Curso" if language == "es" else "Course"
                row[catalog.project] = playlist["titles"].get(video_id, video_id)
                row[catalog.video] = f"https://youtu.be/{video_id}"
                selected.append((catalog, row))
        if not selected:
            continue
        slug = slugify(playlist["title"])
        if slug in used_slugs:
            slug = f"{slug}-{playlist['id'][-6:].lower()}"
        used_slugs.add(slug)
        page_name = f"{slug}.md"
        (page_dir / page_name).write_text(
            render_detail_page(playlist["title"], playlist["id"], selected, language),
            encoding="utf-8",
        )
        section = "Courses" if playlist["course"] and language == "en" else "Playlists"
        if language == "es":
            section = "Cursos" if playlist["course"] else "Listas"
        grouped[language][section].append(
            {
                "title": playlist["title"],
                "page": f"playlists/{page_name}",
                "count": len(selected),
                "id": playlist["id"],
            }
        )
        log.info("Wrote playlist page %s (%s videos)", page_name, len(selected))

    for language, catalog in catalogs.items():
        missing = [
            (catalog, row)
            for video_id, row in rows_for[language].items()
            if video_id not in covered[language]
        ]
        if not missing:
            continue
        title = "Otros videos" if language == "es" else "Other videos"
        page_name = "otros-videos.md" if language == "es" else "other-videos.md"
        (page_dir / page_name).write_text(
            render_detail_page(title, "", missing, language),
            encoding="utf-8",
        )
        section = "Listas" if language == "es" else "Playlists"
        grouped[language][section].append(
            {"title": title, "page": f"playlists/{page_name}", "count": len(missing), "id": ""}
        )

    sections_en = [("Courses", grouped["en"]["Courses"]), ("Playlists", grouped["en"]["Playlists"])]
    sections_es = [("Cursos", grouped["es"]["Cursos"]), ("Listas", grouped["es"]["Listas"])]
    EN_INDEX.write_text(render_playlist_index("en", sections_en), encoding="utf-8")
    ES_INDEX.write_text(render_playlist_index("es", sections_es), encoding="utf-8")
    log.info("Wrote playlist indexes %s and %s", EN_INDEX.name, ES_INDEX.name)


def write_links_workbook() -> None:
    """Collect every catalog CSV into only_readmes/data/links.xlsx."""
    from openpyxl import Workbook

    from llm_notebooks_sync import ES_CSV as LLM_ES_CSV
    from llm_notebooks_sync import EN_CSV as LLM_EN_CSV

    sheets = (
        ("English", EN_CSV),
        ("Spanish", ES_CSV),
        ("LLM English", LLM_EN_CSV),
        ("LLM Spanish", LLM_ES_CSV),
    )
    workbook = Workbook()
    used_active = False
    for title, path in sheets:
        if not path.exists():
            log.warning("Workbook skipped missing CSV %s", path)
            continue
        sheet = workbook.active if not used_active else workbook.create_sheet(title)
        used_active = True
        sheet.title = title
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle):
                sheet.append(row)
        log.info("Workbook sheet %s from %s", title, path)
    destination = ONLY_READMES / "data" / "links.xlsx"
    workbook.save(destination)
    log.info("Wrote %s", destination)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sync YouTube descriptions into the only_readmes and LLM Notebooks catalogs."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the selected catalogs. The default is a dry run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Dry-run only the first N existing rows of each only_readmes CSV. Do not combine with --apply.",
    )
    parser.add_argument(
        "--playlists",
        action="store_true",
        help="Rebuild the main pages as playlist lists and write one detail page per list.",
    )
    parser.add_argument(
        "--catalog",
        choices=("only-readmes", "llm-notebooks", "all"),
        default="all",
        help="only-readmes updates the channel catalog. llm-notebooks writes a separate catalog. all runs both, then links.xlsx.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.apply and args.limit is not None:
        log.error("--limit is for a dry run. Omit --limit when you pass --apply.")
        return 1
    try:
        if args.playlists:
            if args.catalog in {"only-readmes", "all"}:
                build_only_readmes_playlist_pages()
            if args.catalog in {"llm-notebooks", "all"}:
                from llm_notebooks_sync import LlmNotebookSync

                LlmNotebookSync().build_playlist_pages()
            return 0
        if args.catalog in {"only-readmes", "all"}:
            process(apply=args.apply, limit=args.limit)
        if args.catalog in {"llm-notebooks", "all"}:
            from llm_notebooks_sync import LlmNotebookSync

            LlmNotebookSync().run(
                apply=args.apply,
                exclude_ids=video_ids_in_catalog_csvs(),
            )
        if args.apply:
            write_links_workbook()
    except Exception as exc:
        log.exception("Sync failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
