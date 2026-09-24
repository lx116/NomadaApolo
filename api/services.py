import logging
from pathlib import Path

from django.db import transaction

from api.models import Audio, AudioTranscription
from transcriptor.transcriber import transcribe


logger = logging.getLogger(__name__)


def format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def format_transcript(segments: list[dict]) -> str:
    return "\n\n".join(
        f"[{format_timestamp(segment['start'])} - "
        f"{format_timestamp(segment['end'])}]\n{segment['text']}"
        for segment in segments
    )


def transcribe_audio(audio: Audio, transcribe=transcribe, *, claimed=False) -> Audio:
    if not claimed:
        audio.state = "processing"
        audio.save(update_fields=["state", "updated_at"])

    try:
        path = str(Path(audio.audio_file.path).resolve(strict=True))
        result = transcribe(path)

        with transaction.atomic():
            AudioTranscription.objects.update_or_create(
                audio=audio,
                defaults={
                    "raw_content": format_transcript(result["segments"]),
                    "language": result["language"],
                    "state": "completed",
                },
            )
            audio.state = "transcribed"
            audio.save(update_fields=["state", "updated_at"])
    except Exception:
        logger.exception("Failed to transcribe audio %s", audio.pk)
        with transaction.atomic():
            AudioTranscription.objects.update_or_create(
                audio=audio,
                defaults={"raw_content": "", "state": "failed"},
            )
            audio.state = "failed"
            audio.save(update_fields=["state", "updated_at"])

    audio.refresh_from_db()
    return audio
