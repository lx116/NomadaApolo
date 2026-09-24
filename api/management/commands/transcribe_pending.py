import argparse
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from api import services
from api.models import Audio
from api.tasks import publish_transcription


def _positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("must be a positive integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


class Command(BaseCommand):
    help = "Transcribe all pending audio files."

    def add_arguments(self, parser):
        parser.add_argument("--enqueue", action="store_true")
        parser.add_argument("--reset-stale", type=_positive_int, metavar="MINUTES")

    def handle(self, *args, **options):
        reset_stale = options["reset_stale"]
        if reset_stale:
            now = timezone.now()
            reset = Audio.objects.filter(
                state="processing",
                updated_at__lt=now - timedelta(minutes=reset_stale),
            ).update(
                state="pending",
                updated_at=now,
                progress_done=None,
                progress_total=None,
            )
            self.stdout.write(f"{reset} reset to pending")

        if options["enqueue"]:
            audios = Audio.objects.filter(state="pending").order_by("created_at")
            enqueued = sum(
                publish_transcription(str(audio.pk)) for audio in audios
            )
            self.stdout.write(f"{enqueued} enqueued")
            return

        if reset_stale:
            return

        audios = list(Audio.objects.filter(state="pending").order_by("created_at"))
        transcribed = 0
        failed = 0

        for audio in audios:
            result = services.transcribe_audio(audio)
            transcribed += result.state == "transcribed"
            failed += result.state == "failed"
            self.stdout.write(f"{result.title}: {result.state}")

        self.stdout.write(
            f"Processed {len(audios)}: {transcribed} transcribed, {failed} failed"
        )
