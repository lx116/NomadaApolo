from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.urls import reverse
from kombu.exceptions import OperationalError

from api import services, tasks
from api.folder_source import import_audio_files
from api.models import Audio


def upload(name="sample.opus"):
    return SimpleUploadedFile(name, b"audio", content_type="audio/ogg")


@pytest.mark.django_db
def test_api_upload_enqueues_once(client, django_capture_on_commit_callbacks):
    owner = User.objects.create_user(username="api-owner")
    with patch.object(tasks.transcribe_audio_task, "delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(
                "/api/upload/",
                {"owner": owner.pk, "title": "API", "audio_file": upload()},
            )

    audio = Audio.objects.get()
    assert response.status_code == 201
    delay.assert_called_once_with(str(audio.pk))


@pytest.mark.django_db
def test_browser_upload_enqueues_once(client, django_capture_on_commit_callbacks):
    with patch.object(tasks.transcribe_audio_task, "delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(reverse("audio-upload"), {"audio_file": upload()})

    audio = Audio.objects.get()
    assert response.status_code == 302
    delay.assert_called_once_with(str(audio.pk))


@pytest.mark.django_db
@pytest.mark.parametrize("name", ["bad.flac", None])
def test_invalid_browser_upload_does_not_enqueue(
    client, django_capture_on_commit_callbacks, name
):
    data = {"audio_file": upload(name)} if name else {}
    with patch.object(tasks.transcribe_audio_task, "delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            client.post(reverse("audio-upload"), data)

    delay.assert_not_called()
    assert not Audio.objects.exists()


@pytest.mark.django_db
def test_folder_import_enqueues_only_new_file(
    tmp_path, django_capture_on_commit_callbacks
):
    owner = User.objects.create_user(username="owner")
    old = tmp_path / "old.mp3"
    new = tmp_path / "new.mp3"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    Audio.objects.create(owner=owner, title="old", source_path=str(old.resolve()))

    with patch.object(tasks.transcribe_audio_task, "delay") as delay:
        with django_capture_on_commit_callbacks(execute=True):
            imported, skipped = import_audio_files([old, new], tmp_path, owner)

    audio = Audio.objects.get(source_path=str(new.resolve()))
    assert imported == ["new.mp3"]
    assert skipped == [("old.mp3", "already_imported")]
    delay.assert_called_once_with(str(audio.pk))


@pytest.mark.django_db
def test_enqueue_is_discarded_on_rollback():
    owner = User.objects.create_user(username="owner")
    with patch.object(tasks.transcribe_audio_task, "delay") as delay:
        with pytest.raises(RuntimeError), transaction.atomic():
            audio = Audio.objects.create(owner=owner, title="rolled back")
            tasks.enqueue_transcription(audio)
            raise RuntimeError

    delay.assert_not_called()


@pytest.mark.django_db
def test_callback_is_deferred_and_does_not_transcribe_inline(
    client, django_capture_on_commit_callbacks
):
    with (
        patch.object(tasks.transcribe_audio_task, "delay") as delay,
        patch.object(services, "transcribe_audio") as transcribe,
        django_capture_on_commit_callbacks(execute=False) as callbacks,
    ):
        client.post(reverse("audio-upload"), {"audio_file": upload()})

    assert len(callbacks) == 1
    delay.assert_not_called()
    transcribe.assert_not_called()
    assert Audio.objects.get().state == "pending"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("endpoint", "expected_status"), [("browser", 302), ("api", 201)]
)
def test_broker_failure_does_not_fail_upload(
    client, caplog, django_capture_on_commit_callbacks, endpoint, expected_status
):
    if endpoint == "api":
        owner = User.objects.create_user(username="api-owner")
        url = "/api/upload/"
        data = {"owner": owner.pk, "title": "API", "audio_file": upload()}
    else:
        url = reverse("audio-upload")
        data = {"audio_file": upload()}
    with patch.object(
        tasks.transcribe_audio_task, "delay", side_effect=OperationalError("down")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            response = client.post(url, data)

    assert response.status_code == expected_status
    assert Audio.objects.get().state == "pending"
    assert any(record.levelname == "ERROR" for record in caplog.records)


@pytest.mark.django_db
def test_scan_continues_when_broker_is_down(
    tmp_path, django_capture_on_commit_callbacks
):
    owner = User.objects.create_user(username="owner")
    paths = [tmp_path / "one.mp3", tmp_path / "two.mp3"]
    for path in paths:
        path.write_bytes(b"audio")

    with patch.object(
        tasks.transcribe_audio_task, "delay", side_effect=OperationalError("down")
    ):
        with django_capture_on_commit_callbacks(execute=True):
            imported, skipped = import_audio_files(paths, tmp_path, owner)

    assert imported == ["one.mp3", "two.mp3"]
    assert skipped == []
    assert set(Audio.objects.values_list("state", flat=True)) == {"pending"}


def test_publish_transcription_reports_result():
    with patch.object(tasks.transcribe_audio_task, "delay"):
        assert tasks.publish_transcription("ok") is True
    with patch.object(tasks.transcribe_audio_task, "delay", side_effect=Exception):
        assert tasks.publish_transcription("failed") is False
