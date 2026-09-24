from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from api.models import Audio, AudioTranscription
from api.tasks import make_progress_writer, transcribe_audio_task
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
    monkeypatch.setattr("api.services.transcribe", lambda path, **kwargs: successful_result())

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
    monkeypatch.setattr("api.services.transcribe", lambda path, **kwargs: calls.append(path))

    transcribe_audio_task(str(audio.pk))

    audio.refresh_from_db()
    assert audio.state == state
    assert calls == []


@pytest.mark.django_db
def test_sequential_runs_transcribe_once(monkeypatch):
    audio = create_audio()
    calls = []

    def fake(path, **kwargs):
        calls.append(path)
        return successful_result()

    monkeypatch.setattr("api.services.transcribe", fake)

    transcribe_audio_task(str(audio.pk))
    transcribe_audio_task(str(audio.pk))

    assert len(calls) == 1


@pytest.mark.django_db
def test_missing_audio_is_ignored(monkeypatch):
    calls = []
    monkeypatch.setattr("api.services.transcribe", lambda path, **kwargs: calls.append(path))

    transcribe_audio_task(str(uuid4()))

    assert calls == []


@pytest.mark.django_db
def test_malformed_audio_id_is_ignored(monkeypatch):
    calls = []
    monkeypatch.setattr("api.services.transcribe", lambda path, **kwargs: calls.append(path))

    transcribe_audio_task("not-a-uuid")

    assert calls == []


@pytest.mark.django_db
def test_transcription_error_marks_audio_failed(monkeypatch):
    audio = create_audio()

    def fail(path, **kwargs):
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
    monkeypatch.setattr("api.services.transcribe", lambda path, **kwargs: successful_result())
    before = timezone.now()

    transcribe_audio_task(str(audio.pk))

    audio.refresh_from_db()
    assert before <= audio.updated_at <= timezone.now()


@pytest.mark.django_db
def test_writer_first_call_writes():
    audio = create_audio("processing")
    make_progress_writer(audio.pk, clock=lambda: 0.0)(2, 10)
    audio.refresh_from_db()
    assert (audio.progress_done, audio.progress_total) == (2.0, 10.0)


@pytest.mark.django_db
def test_writer_throttles_within_interval_and_writes_after():
    audio = create_audio("processing")
    ticks = iter([0.0, 0.5, 1.0])
    write = make_progress_writer(audio.pk, clock=lambda: next(ticks))
    write(1, 10); write(2, 10)
    audio.refresh_from_db()
    assert audio.progress_done == 1.0
    write(3, 10)
    audio.refresh_from_db()
    assert audio.progress_done == 3.0


@pytest.mark.django_db
def test_writer_never_decreases_done():
    audio = create_audio("processing")
    ticks = iter([0.0, 1.0])
    write = make_progress_writer(audio.pk, clock=lambda: next(ticks))
    write(5, 10); write(3, 10)
    audio.refresh_from_db()
    assert audio.progress_done == 5.0


@pytest.mark.django_db
def test_writer_clamps_done_to_total():
    audio = create_audio("processing")
    make_progress_writer(audio.pk, clock=lambda: 0.0)(12, 10)
    audio.refresh_from_db()
    assert (audio.progress_done, audio.progress_total) == (10.0, 10.0)


@pytest.mark.django_db
def test_writer_unknown_or_zero_total_leaves_total_null():
    for total in (None, 0):
        audio = create_audio("processing")
        make_progress_writer(audio.pk, clock=lambda: 0.0)(2, total)
        audio.refresh_from_db()
        assert (audio.progress_done, audio.progress_total) == (2.0, None)


@pytest.mark.django_db
def test_writer_ignores_non_processing_audio():
    audio = create_audio("pending")
    make_progress_writer(audio.pk, clock=lambda: 0.0)(2, 10)
    audio.refresh_from_db()
    assert (audio.progress_done, audio.progress_total) == (None, None)


@pytest.mark.django_db
def test_writer_advances_updated_at():
    audio = create_audio("processing")
    old = timezone.now() - timedelta(days=1)
    Audio.objects.filter(pk=audio.pk).update(updated_at=old)
    make_progress_writer(audio.pk, clock=lambda: 0.0)(2, 10)
    audio.refresh_from_db()
    assert audio.updated_at > old


@pytest.mark.django_db
def test_writer_swallows_db_error_and_logs(monkeypatch, caplog):
    from django.db.models.query import QuerySet

    audio = create_audio("processing")
    original = QuerySet.update

    def fail_progress(self, **kwargs):
        if "progress_done" in kwargs and "state" not in kwargs:
            raise RuntimeError("db broke")
        return original(self, **kwargs)

    monkeypatch.setattr(QuerySet, "update", fail_progress)
    assert make_progress_writer(audio.pk, clock=lambda: 0.0)(1, 10) is None
    assert "Could not record progress" in caplog.text


@pytest.mark.django_db
def test_task_persists_progress_snapshots(monkeypatch):
    audio = create_audio()
    snapshots = []

    def fake(path, *, on_progress):
        for done in (5.0, 10.0):
            on_progress(done, 20.0)
            snapshots.append(Audio.objects.values_list(
                "state", "progress_done", "progress_total"
            ).get(pk=audio.pk))
        return successful_result()

    ticks = iter([0.0, 1.0])
    monkeypatch.setattr("api.services.transcribe", fake)
    monkeypatch.setattr("api.tasks.monotonic", lambda: next(ticks))
    transcribe_audio_task(str(audio.pk))
    audio.refresh_from_db()
    assert snapshots == [("processing", 5.0, 20.0), ("processing", 10.0, 20.0)]
    assert audio.state == "transcribed"


@pytest.mark.django_db
def test_task_survives_progress_write_failure(monkeypatch):
    from django.db.models.query import QuerySet

    audio = create_audio()
    original = QuerySet.update

    def fail_progress(self, **kwargs):
        if "progress_done" in kwargs and "state" not in kwargs:
            raise RuntimeError("db broke")
        return original(self, **kwargs)

    def fake(path, **kwargs):
        kwargs["on_progress"](1, 10)
        return successful_result()

    monkeypatch.setattr(QuerySet, "update", fail_progress)
    monkeypatch.setattr("api.services.transcribe", fake)
    transcribe_audio_task(str(audio.pk))
    audio.refresh_from_db()
    assert audio.state == "transcribed"


@pytest.mark.django_db
def test_claim_resets_progress(monkeypatch):
    audio = create_audio()
    Audio.objects.filter(pk=audio.pk).update(progress_done=3, progress_total=9)
    observed = []

    def fake(path, **kwargs):
        observed.append(Audio.objects.values_list(
            "progress_done", "progress_total"
        ).get(pk=audio.pk))
        return successful_result()

    monkeypatch.setattr("api.services.transcribe", fake)
    transcribe_audio_task(str(audio.pk))
    assert observed == [(None, None)]


@pytest.mark.django_db
def test_duplicate_task_keeps_progress(monkeypatch):
    audio = create_audio("processing")
    Audio.objects.filter(pk=audio.pk).update(progress_done=3, progress_total=9)
    monkeypatch.setattr("api.services.transcribe", lambda path, **kwargs: successful_result())
    transcribe_audio_task(str(audio.pk))
    audio.refresh_from_db()
    assert (audio.progress_done, audio.progress_total) == (3.0, 9.0)
