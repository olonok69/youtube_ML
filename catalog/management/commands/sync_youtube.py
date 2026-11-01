from django.core.management.base import BaseCommand, CommandError

from catalog.sync import sync_channel
from catalog.youtube_api import YouTubeError


class Command(BaseCommand):
    help = "Copy the channel, its public uploads, today's stats and its playlists into db.sqlite3. Read-only on YouTube."

    def add_arguments(self, parser):
        parser.add_argument("--channel", help="Channel id. Defaults to YOUTUBE_CHANNEL_ID from keys/.env.")
        parser.add_argument("--limit", type=int, help="Stop after this many uploads, newest first.")
        parser.add_argument("--no-playlists", action="store_true", help="Skip playlists and their items.")

    def handle(self, *args, **options):
        try:
            result = sync_channel(
                options["channel"],
                limit=options["limit"],
                playlists=not options["no_playlists"],
            )
        except (YouTubeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(result.summary()))
        if result.skipped:
            self.stdout.write(f"YouTube returned no details for: {', '.join(result.skipped)}")
