from functools import partial
from io import StringIO
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command

from api import services
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
