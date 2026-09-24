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
def test_audio_status_returns_only_public_status_in_newest_first_order(client):
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
            {"id": str(audio.pk), "state": audio.state, "progress": None}
            for audio in reversed(audios)
        ]
    }
    assert all(
        set(item) == {"id", "state", "progress"}
        for item in response.json()["audios"]
    )
    assert b"/private/pending.opus" not in response.content
    assert b"Pending private.opus" not in response.content
    assert b"Pending private" not in response.content


@pytest.mark.django_db
def test_status_processing_progress_payload(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Processing", "processing")
    audio.progress_done = 38.0
    audio.progress_total = 90.0
    audio.save(update_fields=["progress_done", "progress_total"])

    item = client.get(reverse("audio-status")).json()["audios"][0]

    assert item["progress"] == {"done": 38.0, "total": 90.0, "percent": 42}


@pytest.mark.django_db
def test_status_progress_null_outside_processing_or_without_total(client):
    owner = User.objects.create_user(username="owner")
    cases = [
        ("pending", 10.0, 20.0),
        ("transcribed", 10.0, 20.0),
        ("failed", 10.0, 20.0),
        ("processing", 10.0, None),
        ("processing", 10.0, 0.0),
        ("processing", None, 20.0),
    ]
    for index, (state, done, total) in enumerate(cases):
        audio = create_audio(owner, f"Audio {index}", state)
        audio.progress_done = done
        audio.progress_total = total
        audio.save(update_fields=["progress_done", "progress_total"])

    payload = client.get(reverse("audio-status")).json()

    assert all(item["progress"] is None for item in payload["audios"])


@pytest.mark.django_db
def test_status_percent_clamped(client):
    owner = User.objects.create_user(username="owner")
    over = create_audio(owner, "Over", "processing")
    over.progress_done, over.progress_total = 120.0, 90.0
    over.save(update_fields=["progress_done", "progress_total"])
    negative = create_audio(owner, "Negative", "processing")
    negative.progress_done, negative.progress_total = -10.0, 90.0
    negative.save(update_fields=["progress_done", "progress_total"])

    audios = client.get(reverse("audio-status")).json()["audios"]
    by_id = {item["id"]: item["progress"] for item in audios}

    assert by_id[str(over.pk)] == {"done": 90.0, "total": 90.0, "percent": 100}
    assert by_id[str(negative.pk)] == {"done": 0.0, "total": 90.0, "percent": 0}


@pytest.mark.django_db
def test_status_single_query(client, django_assert_num_queries):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Audio", "processing")

    with django_assert_num_queries(1):
        client.get(reverse("audio-status"))


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
