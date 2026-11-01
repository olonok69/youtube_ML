# The channel in db.sqlite3

The site reads YouTube live. `sync_youtube` keeps a copy of the channel in `db.sqlite3`, so other tools can query it with plain SQL. The DuckDB demo attaches this file read-only.

## Fill it

```text
uv run python manage.py migrate
uv run python manage.py sync_youtube
```

The key comes from `keys/.env`, as for the site. Every call is a read with the API key. Options:

- `--limit 20` stops after the 20 newest uploads.
- `--no-playlists` skips playlists.
- `--channel UC...` reads another public channel.

A run costs about 20 quota units for a channel with 200 uploads and 10 playlists. The free daily quota is 10,000.

Run it once a day, from cron or Task Scheduler, to build a history. Each run writes one stats row per video for that day. A second run on the same day overwrites that day's row.

## Tables

| Table | One row per | Key columns |
| --- | --- | --- |
| `catalog_channel` | channel | `id`, `title`, `uploads_playlist_id`, `synced_at` |
| `catalog_channelsnapshot` | channel and day | `taken_on`, `subscriber_count`, `view_count`, `video_count` |
| `catalog_video` | public upload | `id`, `title`, `description`, `published`, `duration_seconds`, `category`, `caption`, `tags` and `topics` (JSON text) |
| `catalog_videostats` | video and day | `taken_on`, `view_count`, `like_count`, `comment_count` |
| `catalog_playlist` | playlist | `id`, `title`, `item_count` |
| `catalog_playlistitem` | video in a playlist | `playlist_id`, `video_id`, `position` |

`catalog_playlistitem.video_id` is plain text, not a foreign key, because a playlist can hold videos from other channels. Private and deleted uploads are skipped. The Django admin at `/admin/` lists every table once you run `createsuperuser`.

## Query it from DuckDB

```sql
INSTALL sqlite; LOAD sqlite;
ATTACH 'db.sqlite3' AS yt (TYPE sqlite, READ_ONLY);

SELECT v.title, s.view_count
FROM yt.catalog_video v
JOIN yt.catalog_videostats s ON s.video_id = v.id
QUALIFY row_number() OVER (PARTITION BY v.id ORDER BY s.taken_on DESC) = 1
ORDER BY s.view_count DESC
LIMIT 10;
```

`tags` is JSON text. `from_json(tags, '["VARCHAR"]')` turns it into a DuckDB list.
