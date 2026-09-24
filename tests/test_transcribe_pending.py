from functools import partial
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.utils import timezone

from datetime import timedelta
from unittest.mock import patch

from api import services, tasks
from api.models import Audio
from transcriptor.transcriber import TranscriptionError


def create_audio(owner, title, state="pending"):
    return Audio.objects.create(
        owner=owner,
        title=title,
        audio_file=SimpleUploadedFile(f"{title}.opus", b"audio"),
        state=state,
    )


def result():
    return {
        "language": "en",
        "duration": 1.0,
        "segments": [{"start": 0.0, "end": 1.0, "text": "Text"}],
        "metrics": {},
    }


def install_fake(monkeypatch, fake):
    original = services.transcribe_audio
    monkeypatch.setattr(services, "transcribe_audio", partial(original, transcribe=fake))


@pytest.mark.django_db
def test_only_pending_processed(monkeypatch):
    owner = User.objects.create_user(username="owner")
    pending = create_audio(owner, "Pending")
    untouched = {
        create_audio(owner, "Failed", "failed"): "failed",
        create_audio(owner, "Transcribed", "transcribed"): "transcribed",
        create_audio(owner, "Processing", "processing"): "processing",
    }
    calls = []

    def fake(path):
        calls.append(path)
        return result()

    install_fake(monkeypatch, fake)
    call_command("transcribe_pending", stdout=StringIO())

    pending.refresh_from_db()
    assert pending.state == "transcribed"
    assert len(calls) == 1
    for audio, original_state in untouched.items():
        audio.refresh_from_db()
        assert audio.state == original_state


@pytest.mark.django_db
def test_nothing_pending_exit_0_zero_processed():
    output = StringIO()

    result_value = call_command("transcribe_pending", stdout=output)

    assert result_value is None
    assert output.getvalue().strip() == "Processed 0: 0 transcribed, 0 failed"


@pytest.mark.django_db
def test_failure_does_not_stop_batch(monkeypatch):
    owner = User.objects.create_user(username="owner")
    first = create_audio(owner, "First")
    second = create_audio(owner, "Second")

    def fake(path):
        if Path(path).name.startswith("First"):
            raise TranscriptionError("first failed")
        return result()

    install_fake(monkeypatch, fake)
    call_command("transcribe_pending", stdout=StringIO())

    first.refresh_from_db()
    second.refresh_from_db()
    assert first.state == "failed"
    assert second.state == "transcribed"


@pytest.mark.django_db
def test_summary_line(monkeypatch):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "One")
    create_audio(owner, "Two")
    install_fake(monkeypatch, lambda path: result())
    output = StringIO()

    call_command("transcribe_pending", stdout=output)

    lines = output.getvalue().splitlines()
    assert len(lines) == 3
    assert "One" in lines[0] and "transcribed" in lines[0]
    assert "Two" in lines[1] and "transcribed" in lines[1]
    assert lines[-1] == "Processed 2: 2 transcribed, 0 failed"


@pytest.mark.django_db
def test_enqueue_only_pending_without_state_changes():
    owner = User.objects.create_user(username="owner")
    pending = [create_audio(owner, str(index)) for index in range(2)]
    others = [create_audio(owner, "processing", "processing"), create_audio(owner, "failed", "failed")]
    with patch.object(tasks.transcribe_audio_task, "delay") as delay:
        call_command("transcribe_pending", "--enqueue", stdout=StringIO())

    assert [call.args[0] for call in delay.call_args_list] == [str(audio.pk) for audio in pending]
    assert list(Audio.objects.order_by("created_at").values_list("state", flat=True)) == ["pending", "pending", "processing", "failed"]


@pytest.mark.django_db
def test_enqueue_with_nothing_pending_reports_zero():
    output = StringIO()
    with patch.object(tasks.transcribe_audio_task, "delay") as delay:
        assert call_command("transcribe_pending", "--enqueue", stdout=output) is None
    delay.assert_not_called()
    assert "0 enqueued" in output.getvalue()


@pytest.mark.django_db
def test_reset_stale_processing_only():
    owner = User.objects.create_user(username="owner")
    old = create_audio(owner, "old", "processing")
    recent = create_audio(owner, "recent", "processing")
    ignored = [create_audio(owner, "failed", "failed"), create_audio(owner, "done", "transcribed")]
    Audio.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(minutes=31))
    Audio.objects.filter(pk=recent.pk).update(updated_at=timezone.now() - timedelta(minutes=29))
    output = StringIO()

    with patch.object(services, "transcribe_audio") as transcribe:
        call_command("transcribe_pending", "--reset-stale", "30", stdout=output)

    old.refresh_from_db(); recent.refresh_from_db()
    assert (old.state, recent.state) == ("pending", "processing")
    assert set(Audio.objects.filter(pk__in=[a.pk for a in ignored]).values_list("state", flat=True)) == {"failed", "transcribed"}
    assert "1 reset to pending" in output.getvalue()
    transcribe.assert_not_called()


@pytest.mark.django_db
def test_reset_stale_reports_zero_for_non_processing_rows():
    owner = User.objects.create_user(username="owner")
    rows = [create_audio(owner, "failed", "failed"), create_audio(owner, "done", "transcribed")]
    Audio.objects.filter(pk__in=[row.pk for row in rows]).update(updated_at=timezone.now() - timedelta(days=1))
    output = StringIO()
    call_command("transcribe_pending", "--reset-stale", "1", stdout=output)
    assert "0 reset" in output.getvalue()


@pytest.mark.django_db
@pytest.mark.parametrize("value", ["abc", "-5", "0"])
def test_reset_stale_rejects_invalid_minutes_without_changes(value):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "old", "processing")
    with pytest.raises(CommandError):
        call_command("transcribe_pending", "--reset-stale", value)
    audio.refresh_from_db()
    assert audio.state == "processing"


@pytest.mark.django_db
def test_reset_then_enqueue_includes_reset_row():
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "old", "processing")
    Audio.objects.filter(pk=audio.pk).update(updated_at=timezone.now() - timedelta(minutes=31))
    with patch.object(tasks.transcribe_audio_task, "delay") as delay:
        call_command("transcribe_pending", "--reset-stale", "30", "--enqueue", stdout=StringIO())
    delay.assert_called_once_with(str(audio.pk))
