# Channel app

The Django app is the screen for the video after the API and the MCP server are working. It reads the same channel and does not write anything back to YouTube.

## Run it

From the repo root, with Python 3.12 and [uv](https://docs.astral.sh/uv/):

```text
uv sync
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/. The API key comes from `keys/.env`. The channel id defaults to `UCqAi1lTsd2wj7p05-Oos4ug`.

## Pages

The left menu is on every page.

**Home** (`/`) is the channel. It shows the latest uploads, twelve at a time, with newer and older pages. The search box stays inside this channel. A video from another channel returns 404. Each card opens the video page.

**Find a video** (`/find/`) takes either a YouTube link or a description.

- A link (`https://youtu.be/...`, a watch URL, or the 11-character id) loads that video. If it is on this channel, it is shown above the list. If it is not, the list is still the closest videos that are.
- A description is compared as text. A long paste that happens to contain a URL is treated as a description, not as a link.
- The list is the closest uploads on this channel. The score is a word overlap between what you pasted and each video's title and description. The first search reads the public uploads once and keeps that list for 30 minutes, so the next search is quick.
- Click a row and the video page opens.

**Video** (`/video/<id>/`) shows the public metadata YouTube returns for that upload: id, channel, date, duration, views, likes, comments, category, definition, captions, languages, privacy, license, embeddable, made for kids, tags, topics, the URL, and the full description. From Find, the back link returns to the same search.

## What a viewer should take from the demo

1. The key in `keys/.env` is enough for the site. No OAuth consent screen, because we never act as the channel.
2. Home is the browse path.
3. Find is the "I have a link or a sentence" path. The similar list is other videos on this channel, not the whole of YouTube.
4. The metadata page is everything the read API gives you for one video, in one place.

## Code map

| File | Role |
| --- | --- |
| `manage.py` | Django entry point |
| `config/settings.py` | Loads `keys/.env`, sets the channel id |
| `catalog/views.py` | Home, find, video |
| `catalog/youtube_api.py` | YouTube calls, similarity, metadata rows |
| `catalog/models.py`, `catalog/sync.py` | The channel as tables in `db.sqlite3`, filled by `manage.py sync_youtube` ([database.md](database.md)) |
| `catalog/templates/catalog/` | Left menu, channel grid, find results, metadata table |
