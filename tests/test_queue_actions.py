from datetime import timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from api import queue_actions, tasks
from api.models import Audio


def create_audio(owner, title, state="pending"):
    return Audio.objects.create(
        owner=owner,
        title=title,
        audio_file=SimpleUploadedFile(f"{title}.opus", b"audio"),
        state=state,
    )


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="queue-owner")


@pytest.mark.django_db
def test_reset_stale_only_resets_old_processing_rows_and_clears_progress(owner):
    now = timezone.now()
    old = create_audio(owner, "old", "processing")
    recent = create_audio(owner, "recent", "processing")
    untouched = [
        create_audio(owner, "pending"),
        create_audio(owner, "transcribed", "transcribed"),
        create_audio(owner, "failed", "failed"),
    ]
    Audio.objects.filter(pk=old.pk).update(
        updated_at=now - timedelta(minutes=31), progress_done=40, progress_total=90
    )
    Audio.objects.filter(pk=recent.pk).update(
        updated_at=now - timedelta(minutes=29), progress_done=10, progress_total=90
    )

    assert queue_actions.reset_stale(30, now=now) == 1

    old.refresh_from_db()
    recent.refresh_from_db()
    assert (old.state, old.progress_done, old.progress_total, old.updated_at) == (
        "pending", None, None, now
    )
    assert (recent.state, recent.progress_done, recent.progress_total) == (
        "processing", 10.0, 90.0
    )
    assert set(Audio.objects.filter(pk__in=[a.pk for a in untouched]).values_list(
        "state", flat=True
    )) == {"pending", "transcribed", "failed"}


@pytest.mark.django_db
def test_enqueue_pending_publishes_oldest_first(owner, monkeypatch):
    audios = [create_audio(owner, str(index)) for index in range(3)]
    calls = []
    monkeypatch.setattr(tasks, "publish_transcription", lambda pk: calls.append(pk) or True)

    result = queue_actions.enqueue_pending()

    assert calls == [str(audio.pk) for audio in audios]
    assert result == {"enqueued": 3, "failed": 0, "broker_ok": True}


@pytest.mark.django_db
def test_enqueue_pending_ignores_non_pending_states(owner, monkeypatch):
    pending = create_audio(owner, "pending")
    for state in ("processing", "transcribed", "failed"):
        create_audio(owner, state, state)
    calls = []
    monkeypatch.setattr(tasks, "publish_transcription", lambda pk: calls.append(pk) or True)

    assert queue_actions.enqueue_pending()["enqueued"] == 1
    assert calls == [str(pending.pk)]


@pytest.mark.django_db
def test_enqueue_pending_stops_at_first_failure(owner):
    audios = [create_audio(owner, str(index)) for index in range(3)]
    calls = []

    def publish(pk):
        calls.append(pk)
        return len(calls) < 2

    assert queue_actions.enqueue_pending(publish) == {
        "enqueued": 1, "failed": 2, "broker_ok": False
    }
    assert calls == [str(audio.pk) for audio in audios[:2]]


@pytest.mark.django_db
def test_enqueue_pending_with_nothing_pending(monkeypatch):
    publish = lambda pk: pytest.fail(f"unexpected publish: {pk}")
    assert queue_actions.enqueue_pending(publish) == {
        "enqueued": 0, "failed": 0, "broker_ok": True
    }


@pytest.mark.django_db
def test_recover_resets_then_enqueues_the_reset_rows(owner):
    audio = create_audio(owner, "stale", "processing")
    Audio.objects.filter(pk=audio.pk).update(
        updated_at=timezone.now() - timedelta(minutes=31)
    )
    calls = []

    result = queue_actions.recover(30, lambda pk: calls.append(pk) or True)

    assert result == {"reset": 1, "enqueued": 1, "failed": 0, "broker_ok": True}
    assert calls == [str(audio.pk)]


@pytest.mark.django_db
def test_queue_enqueue_view_post_returns_json_counts(owner, client, monkeypatch):
    create_audio(owner, "pending")
    monkeypatch.setattr(tasks, "publish_transcription", lambda pk: True)

    response = client.post(reverse("queue-enqueue"))

    assert response.status_code == 200
    assert response.json() == {"reset": 0, "enqueued": 1, "failed": 0, "broker_ok": True}
    assert set(response.json()) == {"reset", "enqueued", "failed", "broker_ok"}


def test_queue_enqueue_view_rejects_get(client):
    assert client.get(reverse("queue-enqueue")).status_code == 405


@pytest.mark.django_db
def test_queue_enqueue_view_enforces_csrf(owner, monkeypatch):
    create_audio(owner, "pending")
    publish = lambda pk: pytest.fail(f"unexpected publish: {pk}")
    monkeypatch.setattr(tasks, "publish_transcription", publish)

    response = Client(enforce_csrf_checks=True).post(reverse("queue-enqueue"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_queue_enqueue_view_leaks_no_titles_or_ids(owner, client, monkeypatch):
    audio = create_audio(owner, "private-recording-title")
    monkeypatch.setattr(tasks, "publish_transcription", lambda pk: True)

    body = client.post(reverse("queue-enqueue")).content.decode()

    assert audio.title not in body
    assert str(audio.pk) not in body


@pytest.mark.django_db
def test_transcribe_pending_output_is_unchanged(owner, monkeypatch):
    stale = create_audio(owner, "stale", "processing")
    create_audio(owner, "pending")
    Audio.objects.filter(pk=stale.pk).update(
        updated_at=timezone.now() - timedelta(minutes=31)
    )
    monkeypatch.setattr(tasks, "publish_transcription", lambda pk: True)
    output = StringIO()

    call_command(
        "transcribe_pending", "--reset-stale", "30", "--enqueue", stdout=output
    )

    assert "1 reset to pending" in output.getvalue()
    assert "2 enqueued" in output.getvalue()
