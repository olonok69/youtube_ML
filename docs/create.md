# Create the app, the MCP server, and the API access

This is the build order for the video. The channel is read-only. Nothing in this repository uploads, edits, or deletes a video.

The channel is [The Machine Learning Engineer](https://www.youtube.com/channel/UCqAi1lTsd2wj7p05-Oos4ug), id `UCqAi1lTsd2wj7p05-Oos4ug`.

`only_readmes` sits in this folder but it is a different git repository. `.gitignore` contains `only_readmes/`, so creating this repo does not take that history with it. Credentials in `keys/.env` and `keys/*.json` are ignored as well.

## 1. YouTube Data API

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. Enable [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com).
3. Create an API key under [Credentials](https://console.cloud.google.com/apis/credentials). Restrict it to YouTube Data API v3.
4. Save it in `keys/.env`. Copy `keys/.env.example` and fill the key:

```text
YOUTUBE_API_KEY=your-key-here
YOUTUBE_CHANNEL_ID=UCqAi1lTsd2wj7p05-Oos4ug
```

5. Optional, for the MCP server: create a service account in the same project, download its JSON into `keys/`, and do not commit that file. Public reads use the scope `https://www.googleapis.com/auth/youtube.readonly`. A service account cannot upload and does not become the channel owner.

A working key returns the channel title from:

```text
https://www.googleapis.com/youtube/v3/channels?part=snippet&id=UCqAi1lTsd2wj7p05-Oos4ug&key=YOUR_KEY
```

More detail is in [youtube-api.md](youtube-api.md).

## 2. Python project and the Django app

From this folder, with Python 3.12 and [uv](https://docs.astral.sh/uv/):

```text
uv init --name youtube-ml --python 3.12
uv add "django>=6,<7" "google-api-python-client>=2.140" "openpyxl>=3.1"
uv run django-admin startproject config .
uv run python manage.py startapp catalog
```

`pyproject.toml` in this repo already has those dependencies. `uv sync` is enough when the files are already here.

Wire the project:

- `config/settings.py` adds `catalog` to `INSTALLED_APPS`, loads `keys/.env`, and sets `YOUTUBE_API_KEY` and `YOUTUBE_CHANNEL_ID`.
- `config/urls.py` mounts `catalog.urls` at `/`.
- `catalog/urls.py` has three routes: `/` home, `/find/` search, `/video/<id>/` metadata.
- `catalog/youtube_api.py` calls YouTube. `list_videos` feeds Home. `find_similar` ranks this channel's uploads against a link or a description. `get_video` loads one video and refuses ids that are not on the channel.
- `catalog/templates/catalog/base.html` is the left menu. `channel.html`, `find.html`, and `video.html` are the three pages.

Run it:

```text
uv sync
uv run python manage.py runserver
```

Open http://127.0.0.1:8000/. Home lists the latest uploads. Find a video accepts a YouTube link or a description and lists the closest videos on this channel. Opening one shows the public metadata and the description.

Page-by-page behavior is in [channel-app.md](channel-app.md).

## 3. MCP server

The server lives in `youtube_mcp/`. It is a small Node program that speaks MCP over stdin and stdout. Node 18 or newer.

Create it with:

```text
mkdir youtube_mcp
cd youtube_mcp
npm init -y
npm install @modelcontextprotocol/sdk google-auth-library zod
npm install -D typescript @types/node
```

`package.json` in this repo already names the package `youtube-mcp-server`, sets `"type": "module"`, and runs `tsc` on install. The TypeScript sources are:

| File | Role |
| --- | --- |
| `src/config.ts` | Reads `keys/.env`. Uses the service account when `YOUTUBE_SERVICE_ACCOUNT_FILE` is set, otherwise the API key |
| `src/youtube-client.ts` | YouTube Data API calls |
| `src/transcript.ts` | Captions, SponsorBlock, replay heatmap |
| `src/utils.ts` | URL parsing and chapter lines |
| `src/index.ts` | MCP tool list and handlers |

Build and check:

```text
cd youtube_mcp
npm install
node dist/index.js
```

The process waits on stdin. That is what an MCP client expects. Stop it with Ctrl+C.

Register it for Claude Code. Use the service-account path or the API key, not both, unless you want the service account to win:

```text
claude mcp add -s user youtube -e "YOUTUBE_SERVICE_ACCOUNT_FILE=D:\repos\youtube_ML\keys\your-service-account.json" '--' node "D:\repos\youtube_ML\youtube_mcp\dist\index.js"
```

The tool list and a channel check are in [mcp-server.md](mcp-server.md).

## 4. This repository, without only_readmes

`.gitignore` already has:

```text
only_readmes/
keys/.env
keys/*.json
```

`only_readmes` keeps the remote [Canal_only_readmes](https://github.com/olonok69/Canal_only_readmes). This folder's git history does not include it. `node_modules/`, `dist/`, `.venv/`, and `logs/` stay local too.

This directory is already a local git repository on `main`. It has no GitHub remote yet.
