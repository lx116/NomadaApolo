import logging

from celery import shared_task
from django.utils import timezone

from api.models import Audio


logger = logging.getLogger(__name__)


@shared_task
def transcribe_audio_task(audio_id: str):
    from django.core.exceptions import ValidationError

    try:
        claimed = Audio.objects.filter(pk=audio_id, state="pending").update(
            state="processing",
            updated_at=timezone.now(),
        )
    except (TypeError, ValueError, ValidationError):
        logger.info("Audio %s could not be claimed for transcription", audio_id)
        return

    if claimed != 1:
        logger.info("Audio %s was not pending; transcription skipped", audio_id)
        return

    from api import services

    audio = Audio.objects.get(pk=audio_id)
    services.transcribe_audio(audio, transcribe=services.transcribe, claimed=True)
