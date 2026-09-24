import uuid
from pathlib import Path

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from api.models import Audio, AudioTranscription


def create_audio(owner, title, state="pending", transcript=None):
    audio = Audio.objects.create(
        owner=owner,
        title=title,
        audio_file=SimpleUploadedFile(f"{title}.opus", b"audio"),
        state=state,
    )
    if transcript is not None:
        AudioTranscription.objects.create(
            audio=audio,
            raw_content=transcript,
            state="completed",
        )
    return audio


@pytest.mark.django_db
def test_root_selects_newest(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Older", "transcribed", "Older transcript")
    create_audio(owner, "Newest", "transcribed", "Newest transcript")

    response = client.get(reverse("audio-list"))

    assert response.status_code == 200
    assert b"Newest transcript" in response.content
    assert b"Older transcript" not in response.content


@pytest.mark.django_db
def test_list_ordered_by_created_at_desc(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Older")
    create_audio(owner, "Newest")

    content = client.get(reverse("audio-list")).content.decode()

    assert content.index("Newest") < content.index("Older")


@pytest.mark.django_db
def test_detail_selects_pk(client):
    owner = User.objects.create_user(username="owner")
    older = create_audio(owner, "Older", "transcribed", "Older transcript")
    create_audio(owner, "Newest", "transcribed", "Newest transcript")

    response = client.get(reverse("audio-detail", args=[older.pk]))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Older" in content
    assert "Newest" in content
    assert "Older transcript" in content
    assert f'href="{reverse("audio-detail", args=[older.pk])}" aria-current="page"' in content


@pytest.mark.django_db
def test_unknown_uuid_404(client):
    response = client.get(reverse("audio-detail", args=[uuid.uuid4()]))

    assert response.status_code == 404


@pytest.mark.django_db
def test_completed_transcript_rendered_and_escaped(client):
    owner = User.objects.create_user(username="owner")
    script = "<script>alert(1)</script>"
    audio = create_audio(owner, "Unsafe", "transcribed", script)

    response = client.get(reverse("audio-detail", args=[audio.pk]))

    assert b"<pre" in response.content
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in response.content
    assert script.encode() not in response.content


@pytest.mark.django_db
def test_failed_shows_badge_no_error_text(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Failed audio", "failed")
    AudioTranscription.objects.create(
        audio=audio,
        raw_content="Sensitive error details",
        state="failed",
    )

    response = client.get(reverse("audio-detail", args=[audio.pk]))

    assert b"failed" in response.content
    assert b"Transcription failed" in response.content
    assert b"Sensitive error details" not in response.content


@pytest.mark.django_db
def test_badges_per_state(client):
    owner = User.objects.create_user(username="owner")
    for state in ("pending", "processing", "transcribed", "failed"):
        create_audio(owner, state.title(), state)

    content = client.get(reverse("audio-list")).content

    for state in (b"pending", b"processing", b"transcribed", b"failed"):
        assert state in content


@pytest.mark.django_db
def test_empty_list_200_empty_state(client):
    response = client.get(reverse("audio-list"))

    assert response.status_code == 200
    assert b"No audios yet" in response.content
    assert b"python manage.py transcribe_pending" in response.content


@pytest.mark.django_db
def test_pending_shows_not_transcribed_yet(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Pending audio")

    response = client.get(reverse("audio-detail", args=[audio.pk]))

    assert response.status_code == 200
    assert b"Not transcribed yet" in response.content
    assert b"python manage.py transcribe_pending" in response.content


@pytest.mark.django_db
def test_transcribed_without_row_renders_200(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Missing transcript", "transcribed")

    response = client.get(reverse("audio-detail", args=[audio.pk]))

    assert response.status_code == 200
    assert b"Not transcribed yet" in response.content


def test_tailwind_cdn_only_in_base(settings):
    templates = Path(settings.BASE_DIR) / "templates"
    needle = "cdn.jsdelivr.net/npm/@tailwindcss/browser"
    containing_files = [
        path.relative_to(templates).as_posix()
        for path in templates.rglob("*.html")
        if needle in path.read_text()
    ]

    assert containing_files == ["base.html"]
