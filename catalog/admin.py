from django.contrib import admin

from .models import Channel, ChannelSnapshot, Playlist, PlaylistItem, Video, VideoStats


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ("title", "id", "country", "synced_at")


@admin.register(ChannelSnapshot)
class ChannelSnapshotAdmin(admin.ModelAdmin):
    list_display = ("channel", "taken_on", "subscriber_count", "view_count", "video_count")


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("title", "id", "published", "duration_seconds", "category")
    search_fields = ("title", "description")
    list_filter = ("category", "definition", "caption")


@admin.register(VideoStats)
class VideoStatsAdmin(admin.ModelAdmin):
    list_display = ("video", "taken_on", "view_count", "like_count", "comment_count")


@admin.register(Playlist)
class PlaylistAdmin(admin.ModelAdmin):
    list_display = ("title", "id", "item_count", "published")


@admin.register(PlaylistItem)
class PlaylistItemAdmin(admin.ModelAdmin):
    list_display = ("playlist", "position", "video_id", "added")
