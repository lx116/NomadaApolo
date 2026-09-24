import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from api.models import Audio, AudioTranscription


def create_audio(owner, title, state="pending", source_path=None):
    return Audio.objects.create(
        owner=owner,
        title=title,
        audio_file=SimpleUploadedFile(f"{title}.opus", b"audio"),
        source_path=source_path,
        state=state,
    )


@pytest.mark.django_db
def test_audio_status_returns_only_ids_and_states_in_newest_first_order(client):
    owner = User.objects.create_user(username="owner")
    audios = [
        create_audio(owner, "Pending private", "pending", "/private/pending.opus"),
        create_audio(owner, "Processing private", "processing"),
        create_audio(owner, "Transcribed private", "transcribed"),
        create_audio(owner, "Failed private", "failed"),
    ]

    response = client.get(reverse("audio-status"))

    assert response.status_code == 200
    assert response.headers["Content-Type"].startswith("application/json")
    assert response.json() == {
        "audios": [
            {"id": str(audio.pk), "state": audio.state}
            for audio in reversed(audios)
        ]
    }
    assert all(set(item) == {"id", "state"} for item in response.json()["audios"])
    assert b"/private/pending.opus" not in response.content
    assert b"Pending private.opus" not in response.content
    assert b"Pending private" not in response.content


@pytest.mark.django_db
def test_audio_status_returns_empty_list(client):
    response = client.get(reverse("audio-status"))

    assert response.status_code == 200
    assert response.json() == {"audios": []}


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_audio_status_rejects_non_get_methods(client, method):
    response = getattr(client, method)(reverse("audio-status"))

    assert response.status_code == 405


@pytest.mark.django_db
def test_audio_status_get_creates_no_rows(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Existing")
    before = (Audio.objects.count(), AudioTranscription.objects.count())

    client.get(reverse("audio-status"))

    assert (Audio.objects.count(), AudioTranscription.objects.count()) == before


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["pending", "processing"])
def test_active_audio_renders_status_poller(client, state):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Active", state)

    content = client.get(reverse("audio-list")).content

    assert b'id="audio-states"' in content
    assert b"3000" in content
    assert b"/audios/status/" in content


@pytest.mark.django_db
def test_inactive_audios_do_not_render_status_poller(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Transcribed", "transcribed")
    create_audio(owner, "Failed", "failed")

    content = client.get(reverse("audio-list")).content

    assert b"audio-states" not in content
    assert b"setTimeout" not in content


@pytest.mark.django_db
def test_empty_list_does_not_render_status_poller(client):
    content = client.get(reverse("audio-list")).content

    assert b"audio-states" not in content
    assert b"setTimeout" not in content
