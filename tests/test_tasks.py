from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from api.models import Audio, AudioTranscription
from api.tasks import transcribe_audio_task
from transcriptor.transcriber import TranscriptionError


def create_audio(state="pending"):
    owner = User.objects.create_user(username=f"owner-{uuid4()}")
    return Audio.objects.create(
        owner=owner,
        title="Recording",
        audio_file=SimpleUploadedFile("recording.opus", b"audio"),
        state=state,
    )


def successful_result():
    return {
        "language": "es",
        "duration": 5.0,
        "segments": [
            {"start": 0.2, "end": 2.9, "text": "First block"},
            {"start": 3.0, "end": 5.0, "text": "Second block"},
        ],
        "metrics": {},
    }


@pytest.mark.django_db
def test_pending_audio_is_transcribed(monkeypatch):
    audio = create_audio()
    monkeypatch.setattr("api.services.transcribe", lambda path: successful_result())

    transcribe_audio_task(str(audio.pk))

    audio.refresh_from_db()
    transcription = AudioTranscription.objects.get(audio=audio)
    assert audio.state == "transcribed"
    assert transcription.state == "completed"
    assert transcription.raw_content.count("[") == 2


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["processing", "transcribed", "failed"])
def test_non_pending_audio_is_unchanged(monkeypatch, state):
    audio = create_audio(state=state)
    calls = []
    monkeypatch.setattr("api.services.transcribe", lambda path: calls.append(path))

    transcribe_audio_task(str(audio.pk))

    audio.refresh_from_db()
    assert audio.state == state
    assert calls == []


@pytest.mark.django_db
def test_sequential_runs_transcribe_once(monkeypatch):
    audio = create_audio()
    calls = []

    def fake(path):
        calls.append(path)
        return successful_result()

    monkeypatch.setattr("api.services.transcribe", fake)

    transcribe_audio_task(str(audio.pk))
    transcribe_audio_task(str(audio.pk))

    assert len(calls) == 1


@pytest.mark.django_db
def test_missing_audio_is_ignored(monkeypatch):
    calls = []
    monkeypatch.setattr("api.services.transcribe", lambda path: calls.append(path))

    transcribe_audio_task(str(uuid4()))

    assert calls == []


@pytest.mark.django_db
def test_malformed_audio_id_is_ignored(monkeypatch):
    calls = []
    monkeypatch.setattr("api.services.transcribe", lambda path: calls.append(path))

    transcribe_audio_task("not-a-uuid")

    assert calls == []


@pytest.mark.django_db
def test_transcription_error_marks_audio_failed(monkeypatch):
    audio = create_audio()

    def fail(path):
        raise TranscriptionError("transcription failed")

    monkeypatch.setattr("api.services.transcribe", fail)

    transcribe_audio_task(str(audio.pk))

    audio.refresh_from_db()
    assert audio.state == "failed"
    assert AudioTranscription.objects.get(audio=audio).state == "failed"
    assert not AudioTranscription.objects.filter(audio=audio, state="completed").exists()


@pytest.mark.django_db
def test_claim_refreshes_updated_at(monkeypatch):
    audio = create_audio()
    old_updated_at = timezone.now() - timedelta(days=1)
    Audio.objects.filter(pk=audio.pk).update(updated_at=old_updated_at)
    monkeypatch.setattr("api.services.transcribe", lambda path: successful_result())
    before = timezone.now()

    transcribe_audio_task(str(audio.pk))

    audio.refresh_from_db()
    assert before <= audio.updated_at <= timezone.now()
