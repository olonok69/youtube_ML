"""The channel as rows in db.sqlite3.

`python manage.py sync_youtube` fills these tables from the YouTube Data API. The
site still reads YouTube live; these tables are the copy other tools query (the
DuckDB demo attaches this file read-only). Table names are Django's defaults:
catalog_channel, catalog_channelsnapshot, catalog_video, catalog_videostats,
catalog_playlist and catalog_playlistitem.
"""

from django.db import models


class Channel(models.Model):
    id = models.CharField(primary_key=True, max_length=32)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    custom_url = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=8, blank=True)
    published = models.DateTimeField(null=True)
    thumbnail = models.URLField(max_length=500, blank=True)
    uploads_playlist_id = models.CharField(max_length=64, blank=True)
    synced_at = models.DateTimeField(null=True)

    def __str__(self):
        return self.title


class ChannelSnapshot(models.Model):
    """Channel totals on one day. A second sync on the same day overwrites that day."""

    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="snapshots")
    taken_on = models.DateField()
    subscriber_count = models.BigIntegerField(default=0)
    view_count = models.BigIntegerField(default=0)
    video_count = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["channel", "taken_on"], name="one_channel_snapshot_per_day"),
        ]
        ordering = ["-taken_on"]


class Video(models.Model):
    id = models.CharField(primary_key=True, max_length=11)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="videos")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    published = models.DateTimeField(null=True, db_index=True)
    duration_seconds = models.IntegerField(default=0)
    category_id = models.CharField(max_length=8, blank=True)
    category = models.CharField(max_length=60, blank=True)
    language = models.CharField(max_length=16, blank=True)
    audio_language = models.CharField(max_length=16, blank=True)
    definition = models.CharField(max_length=8, blank=True)
    caption = models.BooleanField(default=False)
    licensed_content = models.BooleanField(null=True)
    privacy_status = models.CharField(max_length=16, blank=True)
    license = models.CharField(max_length=32, blank=True)
    embeddable = models.BooleanField(null=True)
    made_for_kids = models.BooleanField(null=True)
    thumbnail = models.URLField(max_length=500, blank=True)
    # Lists stored as JSON text in SQLite. DuckDB reads them with its json functions.
    tags = models.JSONField(default=list, blank=True)
    topics = models.JSONField(default=list, blank=True)
    synced_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ["-published"]

    def __str__(self):
        return self.title

    @property
    def url(self):
        return f"https://www.youtube.com/watch?v={self.id}"


class VideoStats(models.Model):
    """Public counts for one video on one day. Running the sync daily builds a time series."""

    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="stats")
    taken_on = models.DateField()
    view_count = models.BigIntegerField(default=0)
    like_count = models.BigIntegerField(default=0)
    comment_count = models.BigIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["video", "taken_on"], name="one_video_stats_per_day"),
        ]
        ordering = ["-taken_on"]
        verbose_name_plural = "video stats"


class Playlist(models.Model):
    id = models.CharField(primary_key=True, max_length=64)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="playlists")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    published = models.DateTimeField(null=True)
    item_count = models.IntegerField(default=0)
    privacy_status = models.CharField(max_length=16, blank=True)
    synced_at = models.DateTimeField(null=True)

    def __str__(self):
        return self.title


class PlaylistItem(models.Model):
    """A video's place in a playlist. `video_id` is kept as text: a playlist can hold
    videos from other channels, which are not in the video table."""

    playlist = models.ForeignKey(Playlist, on_delete=models.CASCADE, related_name="items")
    video_id = models.CharField(max_length=11, db_index=True)
    position = models.IntegerField()
    added = models.DateTimeField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["playlist", "position"], name="one_item_per_position"),
        ]
        ordering = ["playlist", "position"]
