from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from api.models import Audio, AudioTranscription
from api.services import format_timestamp, format_transcript, transcribe_audio
from transcriptor.transcriber import TranscriptionError


def create_audio(title="Recording"):
    owner = User.objects.create_user(username=f"owner-{title}")
    return Audio.objects.create(
        owner=owner,
        title=title,
        audio_file=SimpleUploadedFile(f"{title}.opus", b"audio"),
    )


def successful_result():
    return {
        "language": "es",
        "duration": 5.0,
        "segments": [
            {"start": 0.2, "end": 2.9, "text": "First block"},
            {"start": 3661.9, "end": 3663.1, "text": "Second block"},
        ],
        "metrics": {},
    }


def test_format_timestamp():
    assert format_timestamp(0) == "00:00:00"
    assert format_timestamp(59.9) == "00:00:59"
    assert format_timestamp(3661.9) == "01:01:01"


def test_format_transcript_blocks():
    assert format_transcript(successful_result()["segments"]) == (
        "[00:00:00 - 00:00:02]\nFirst block\n\n"
        "[01:01:01 - 01:01:03]\nSecond block"
    )


@pytest.mark.django_db
def test_success_sets_states_language_and_two_blocks():
    audio = create_audio()

    result = transcribe_audio(audio, transcribe=lambda path: successful_result())

    transcription = AudioTranscription.objects.get(audio=audio)
    assert result.state == "transcribed"
    assert transcription.state == "completed"
    assert transcription.language == "es"
    assert transcription.raw_content.count("[") == 2
    assert "First block\n\n[01:01:01 - 01:01:03]" in transcription.raw_content


@pytest.mark.django_db
def test_rerun_upserts_single_transcription():
    audio = create_audio()

    transcribe_audio(audio, transcribe=lambda path: successful_result())
    transcribe_audio(audio, transcribe=lambda path: successful_result())

    assert AudioTranscription.objects.filter(audio=audio).count() == 1


@pytest.mark.django_db
def test_fake_receives_absolute_path():
    audio = create_audio()
    received = []

    def fake(path):
        received.append(path)
        return successful_result()

    transcribe_audio(audio, transcribe=fake)

    assert len(received) == 1
    assert isinstance(received[0], str)
    assert Path(received[0]).is_absolute()
    assert Path(received[0]).is_file()


@pytest.mark.django_db
def test_transcriber_raises_marks_failed_no_completed():
    audio = create_audio()

    def fail(path):
        raise TranscriptionError("transcription failed")

    result = transcribe_audio(audio, transcribe=fail)

    transcription = AudioTranscription.objects.get(audio=audio)
    assert result.state == "failed"
    assert transcription.state == "failed"
    assert transcription.raw_content == ""
    assert not AudioTranscription.objects.filter(audio=audio, state="completed").exists()


@pytest.mark.django_db
def test_missing_file_marks_failed():
    audio = create_audio()
    Path(audio.audio_file.path).unlink()

    result = transcribe_audio(audio, transcribe=lambda path: successful_result())

    assert result.state == "failed"
    assert AudioTranscription.objects.get(audio=audio).state == "failed"
