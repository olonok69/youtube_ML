# YouTube channel tools

These notes are the script for a video about this repository. The channel is [The Machine Learning Engineer](https://www.youtube.com/channel/UCqAi1lTsd2wj7p05-Oos4ug) (`UCqAi1lTsd2wj7p05-Oos4ug`, `@themachinelearningengineer`).

YouTube is read-only. Nothing here uploads, edits, or deletes a video.

## What to show

1. [Get access to the YouTube Data API](youtube-api.md). An API key, and a service account when you want the MCP server to use one.
2. [The MCP server](mcp-server.md). `youtube_mcp` reads the channel from Claude or any other MCP client.
3. [The channel app](channel-app.md). The Django site built in this repo: the channel home, find-by-link-or-description, and the full metadata page.

## What this repository is

| Path | Role |
| --- | --- |
| `docs/` | These notes |
| `youtube_mcp/` | MCP server. Node, TypeScript |
| `catalog/`, `config/`, `manage.py` | Django channel app |
| `sync_channel.py`, `llm_notebooks_sync.py` | Catalog sync. Separate from the video |
| `keys/` | Local credentials. Not committed |

`only_readmes` is its own git repository, [Canal_only_readmes](https://github.com/olonok69/Canal_only_readmes). It is ignored here so the two histories stay apart. The public notebooks stay in [LLM_Notebooks](https://github.com/olonok69/LLM_Notebooks), which lives outside this folder.
