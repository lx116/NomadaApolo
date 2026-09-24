from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from api.models import Audio, AudioTranscription
from api.validartors import validate_audio_file


def uploaded_file(name="sample.opus", content_type="audio/ogg"):
    return SimpleUploadedFile(name, b"audio data", content_type=content_type)


@pytest.mark.django_db
def test_get_200(client):
    response = client.get(reverse("audio-upload"))

    assert response.status_code == 200
    assert b'<form method="post" enctype="multipart/form-data">' in response.content
    assert b"csrfmiddlewaretoken" in response.content


@pytest.mark.django_db
def test_opus_upload_creates_pending_owned_by_local_and_redirects_with_message(client):
    assert not User.objects.exists()

    response = client.post(
        reverse("audio-upload"),
        {"title": "Field recording", "audio_file": uploaded_file()},
    )

    assert response.status_code == 302
    assert response.url == reverse("audio-list")
    audio = Audio.objects.get()
    assert audio.state == "pending"
    assert audio.owner.username == "local"
    followed = client.get(response.url)
    assert b"uploaded" in followed.content.lower()


@pytest.mark.django_db
def test_file_stored_under_media_audio(client):
    client.post(reverse("audio-upload"), {"audio_file": uploaded_file()})

    audio = Audio.objects.get()
    assert audio.audio_file.name.startswith("audio/")
    assert (Path(settings.MEDIA_ROOT) / audio.audio_file.name).exists()


@pytest.mark.django_db
def test_owner_reused(client):
    url = reverse("audio-upload")
    client.post(url, {"audio_file": uploaded_file("first.opus")})
    client.post(url, {"audio_file": uploaded_file("second.opus")})

    assert User.objects.filter(username="local").count() == 1
    assert Audio.objects.count() == 2


@pytest.mark.django_db
def test_missing_csrf_403():
    client = Client(enforce_csrf_checks=True)

    response = client.post(
        reverse("audio-upload"), {"audio_file": uploaded_file()}
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_no_inline_transcription(client):
    client.post(reverse("audio-upload"), {"audio_file": uploaded_file()})

    assert Audio.objects.get().state == "pending"
    assert not AudioTranscription.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("name", "content_type"),
    [("sample.flac", "audio/flac"), ("sample.txt", "text/plain")],
)
def test_flac_and_txt_rejected_no_audio(client, name, content_type):
    response = client.post(
        reverse("audio-upload"),
        {"audio_file": uploaded_file(name, content_type)},
    )

    assert response.status_code == 200
    assert b"supported" in response.content.lower()
    assert not Audio.objects.exists()


@pytest.mark.django_db
def test_no_file_form_error(client):
    response = client.post(reverse("audio-upload"), {"title": "Missing file"})

    assert response.status_code == 200
    assert b"This field is required" in response.content
    assert not Audio.objects.exists()


def test_api_validator_accepts_opus_rejects_flac():
    validate_audio_file(uploaded_file())

    with pytest.raises(ValidationError):
        validate_audio_file(uploaded_file("a.flac", "audio/flac"))
