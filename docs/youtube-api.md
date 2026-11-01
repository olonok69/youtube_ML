# Get access to the YouTube Data API

Public channel, video, playlist, and comment reads use the YouTube Data API v3. Pick one credential. The Django app uses the API key. The MCP server uses a service account when that file is set, and otherwise the same API key.

A service account can read public data. It cannot upload, and it cannot act as the channel owner. That is the right credential for this project, because the channel stays read-only.

## 1. Create the Google Cloud project

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create a project, or select the one you already use for this channel.
2. Open [YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) and enable it on that project.
3. Billing does not have to be on for read calls, but the daily quota still applies. A default project has 10,000 units per day. `videos.list`, `channels.list`, and `playlistItems.list` cost 1 unit per call. `search.list` costs 100.

## 2. Create an API key

1. Go to [APIs & Services, Credentials](https://console.cloud.google.com/apis/credentials).
2. Create credentials, then API key.
3. Restrict the key to the YouTube Data API v3. An unrestricted key works, and it is also the key you do not want to commit.
4. Copy the key into `keys/.env` at the root of this repo:

```text
YOUTUBE_API_KEY=your-key-here
YOUTUBE_CHANNEL_ID=UCqAi1lTsd2wj7p05-Oos4ug
```

`keys/.env` is gitignored. The file is read by Django (`config/settings.py`) and by the MCP server (`youtube_mcp/src/config.ts`).

Check the key with the channel itself. A 200 and the channel title means the key and the API are both on:

```text
https://www.googleapis.com/youtube/v3/channels?part=snippet&id=UCqAi1lTsd2wj7p05-Oos4ug&key=YOUR_KEY
```

Do not paste that URL, with a real key, into a public description or a slide.

## 3. Create a service account

Use this when the MCP server should authenticate with a Google identity instead of a query-string key.

1. In the same project, go to IAM and admin, then Service accounts, and create a service account.
2. No extra IAM role is required for public YouTube reads. The YouTube API has to be enabled on the project. The account does not become a manager of the YouTube channel.
3. Open the service account, Keys, Add key, JSON. Save the downloaded file under `keys/`. Do not commit it. `keys/*.json` is gitignored.
4. Point the process at that file. The MCP server checks this variable before the API key:

```text
YOUTUBE_SERVICE_ACCOUNT_FILE=D:\repos\youtube_ML\keys\your-service-account.json
```

The server exchanges the JSON for an OAuth access token with the scope `https://www.googleapis.com/auth/youtube.readonly` and sends `Authorization: Bearer`.

## Which credential is in use

| Program | Credential |
| --- | --- |
| Django channel app | `YOUTUBE_API_KEY` from `keys/.env` |
| MCP server | Service account if `YOUTUBE_SERVICE_ACCOUNT_FILE` is set, otherwise the API key |
| `sync_channel.py` | The API key for YouTube. A GitHub token in `keys/.env` is only for downloading READMEs |

If both MCP credentials are set, the service account wins.
