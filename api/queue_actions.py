from datetime import timedelta

from django.utils import timezone

from api import tasks
from api.models import Audio


def reset_stale(minutes: int, now=None) -> int:
    now = now or timezone.now()
    return Audio.objects.filter(
        state="processing",
        updated_at__lt=now - timedelta(minutes=minutes),
    ).update(
        state="pending",
        updated_at=now,
        progress_done=None,
        progress_total=None,
    )


def enqueue_pending(publish=None) -> dict:
    publish = publish or tasks.publish_transcription
    ids = [
        str(pk)
        for pk in Audio.objects.filter(state="pending")
        .order_by("created_at")
        .values_list("pk", flat=True)
    ]
    enqueued = 0
    for audio_id in ids:
        if not publish(audio_id):
            return {
                "enqueued": enqueued,
                "failed": len(ids) - enqueued,
                "broker_ok": False,
            }
        enqueued += 1
    return {"enqueued": enqueued, "failed": 0, "broker_ok": True}


def recover(minutes: int, publish=None) -> dict:
    reset = reset_stale(minutes)
    return {"reset": reset, **enqueue_pending(publish)}
