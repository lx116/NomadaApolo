from django.core.management.base import BaseCommand

from api import services
from api.models import Audio


class Command(BaseCommand):
    help = "Transcribe all pending audio files."

    def handle(self, *args, **options):
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
