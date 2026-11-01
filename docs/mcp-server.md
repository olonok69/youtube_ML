# MCP server

`youtube_mcp/` is the Model Context Protocol server for the channel. It speaks stdin/stdout, so Claude, Cursor, or any other MCP client can call it. It only reads YouTube.

The original checkout of `claude-code-youtube-mcp` is not part of this repo. The server we run is this folder.

## Build

From `youtube_mcp`, with Node 18 or newer:

```text
npm install
```

`npm install` compiles TypeScript to `youtube_mcp/dist/index.js`. That `dist` folder and `node_modules` stay local.

On startup the server reads `keys/.env` from the repo root. You do not have to export the API key if it is already in that file. Set `YOUTUBE_SERVICE_ACCOUNT_FILE` in the MCP client when you want the service account.

## Register it

User scope makes the server available in every project. Replace the JSON path with the key you downloaded.

PowerShell:

```text
claude mcp add -s user youtube -e "YOUTUBE_SERVICE_ACCOUNT_FILE=D:\repos\youtube_ML\keys\your-service-account.json" '--' node "D:\repos\youtube_ML\youtube_mcp\dist\index.js"
```

API key instead of a service account:

```text
claude mcp add -s user youtube -e "YOUTUBE_API_KEY=YOUR_API_KEY" '--' node "D:\repos\youtube_ML\youtube_mcp\dist\index.js"
```

Restart the client, then `claude mcp list` should show `youtube`.

## What it can read

Transcripts do not need the Data API. Search, metadata, playlists, comments, and channel stats do.

| Tool | What it returns |
| --- | --- |
| `parse_youtube_url` | Video id, channel id, playlist id, or handle from a URL |
| `get_transcript` | Captions with timestamps |
| `search_transcript` | Where a phrase appears in the captions |
| `get_clean_transcript` | Captions with sponsor reads removed via SponsorBlock |
| `extract_chapters` | Chapters parsed from the description |
| `get_most_replayed` | Replay heatmap, when YouTube publishes one |
| `get_video_metadata` | Title, description, duration, counts, tags |
| `get_channel_info` | Title, subscribers, video count, country |
| `get_channel_videos` | Recent uploads |
| `get_playlist_items` | Videos on a playlist |
| `search_videos` | Public search with date, duration, and sort |
| `search_within_channel` | Search inside one channel |
| `get_trending_videos` | Trending videos by region |
| `get_video_comments` | Top-level comments |
| `calculate_engagement` | Like rate and comment rate from public counts |

A useful on-camera check is `get_channel_info` with `UCqAi1lTsd2wj7p05-Oos4ug`. The title comes back as The Machine Learning Engineer.
