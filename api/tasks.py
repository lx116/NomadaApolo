import logging
from functools import partial
from time import monotonic

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from api.models import Audio


logger = logging.getLogger(__name__)
PROGRESS_INTERVAL_S = 1.0


def make_progress_writer(audio_id, *, interval=PROGRESS_INTERVAL_S, clock=None):
    last = {"at": None, "done": 0.0}

    def write(done, total):
        try:
            total = float(total) if total is not None and total > 0 else None
            done = max(float(done), 0.0, last["done"])
            if total is not None:
                done = min(done, total)
            last["done"] = done
            now = (clock or monotonic)()
            if last["at"] is not None and now - last["at"] < interval:
                return
            last["at"] = now
            Audio.objects.filter(pk=audio_id, state="processing").update(
                progress_done=done,
                progress_total=total,
                updated_at=timezone.now(),
            )
        except Exception:
            logger.exception("Could not record progress for audio %s", audio_id)

    return write


@shared_task
def transcribe_audio_task(audio_id: str):
    from django.core.exceptions import ValidationError

    try:
        claimed = Audio.objects.filter(pk=audio_id, state="pending").update(
            state="processing",
            updated_at=timezone.now(),
            progress_done=None,
            progress_total=None,
        )
    except (TypeError, ValueError, ValidationError):
        logger.info("Audio %s could not be claimed for transcription", audio_id)
        return

    if claimed != 1:
        logger.info("Audio %s was not pending; transcription skipped", audio_id)
        return

    from api import services

    audio = Audio.objects.get(pk=audio_id)
    services.transcribe_audio(
        audio,
        transcribe=services.transcribe,
        claimed=True,
        on_progress=make_progress_writer(audio.pk),
    )


def publish_transcription(audio_id: str) -> bool:
    try:
        transcribe_audio_task.delay(audio_id)
    except Exception:
        logger.exception("Unable to publish transcription for audio %s", audio_id)
        return False
    return True


def enqueue_transcription(audio) -> None:
    transaction.on_commit(
        partial(publish_transcription, str(audio.pk)),
        robust=True,
    )
