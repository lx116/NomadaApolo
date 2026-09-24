import argparse

from django.core.management.base import BaseCommand

from api import queue_actions, services
from api.models import Audio


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
            reset = queue_actions.reset_stale(reset_stale)
            self.stdout.write(f"{reset} reset to pending")

        if options["enqueue"]:
            result = queue_actions.enqueue_pending()
            self.stdout.write(f"{result['enqueued']} enqueued")
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
