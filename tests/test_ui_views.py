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
    assert b"python manage.py transcribe_pending" not in response.content


@pytest.mark.django_db
def test_pending_shows_queued_status(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Pending audio")

    response = client.get(reverse("audio-detail", args=[audio.pk]))

    assert response.status_code == 200
    assert b"Queued for transcription" in response.content
    assert b"Make sure the Celery worker is running" in response.content
    assert b"python manage.py transcribe_pending" not in response.content


@pytest.mark.django_db
def test_processing_shows_transcribing_without_transcript(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Processing audio", "processing")

    response = client.get(reverse("audio-detail", args=[audio.pk]))

    assert response.status_code == 200
    assert b"Transcribing..." in response.content
    assert b"<pre" not in response.content


@pytest.mark.django_db
def test_processing_shows_progressbar(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Processing audio", "processing")
    audio.progress_done, audio.progress_total = 38.0, 90.0
    audio.save(update_fields=["progress_done", "progress_total"])

    content = client.get(reverse("audio-detail", args=[audio.pk])).content.decode()

    assert 'role="progressbar"' in content
    assert 'aria-valuenow="42"' in content
    assert 'aria-valuemin="0"' in content
    assert 'aria-valuemax="100"' in content
    assert "42% – 00:38 of 01:30" in content
    assert f'data-progress-for="{audio.pk}"' in content
    assert "Transcribing..." in content


@pytest.mark.django_db
def test_processing_without_progress_shows_preparing(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Processing audio", "processing")

    content = client.get(reverse("audio-detail", args=[audio.pk])).content.decode()

    assert "Preparing…" in content
    assert 'role="progressbar"' in content
    progressbar = content.split('<div role="progressbar"', 1)[1].split(">", 1)[0]
    assert "aria-valuenow" not in progressbar


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["pending", "transcribed", "failed"])
def test_no_progressbar_when_not_processing(client, state):
    owner = User.objects.create_user(username=f"owner-{state}")
    audio = create_audio(owner, state.title(), state)

    content = client.get(reverse("audio-detail", args=[audio.pk])).content.decode()

    assert '<div role="progressbar"' not in content


def test_format_clock():
    from api.ui_views import format_clock

    assert format_clock(3725) == "1:02:05"
    assert format_clock(38) == "00:38"


@pytest.mark.django_db
def test_active_page_poller_contract(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Processing", "processing")

    content = client.get(reverse("audio-detail", args=[audio.pk])).content.decode()

    assert "data-progress-for" in content
    assert "sessionStorage.setItem" in content
    assert "location.reload" in content
    assert "3000" in content
    assert reverse("audio-status") in content


@pytest.mark.django_db
def test_inactive_page_has_ready_region_but_no_polling(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Transcribed", "transcribed", "Transcript")

    content = client.get(reverse("audio-detail", args=[audio.pk])).content.decode()

    assert 'id="transcript-ready"' in content
    assert 'aria-live="polite"' in content
    assert "Transcript ready" in content
    assert "sessionStorage.removeItem" in content
    assert "setTimeout" not in content
    assert "audio-states" not in content
    assert reverse("audio-status") not in content


@pytest.mark.django_db
def test_failed_transcript_area_has_no_retry_control(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Failed audio", "failed")

    content = client.get(reverse("audio-detail", args=[audio.pk])).content
    transcript_area = content.split(b"<h2", 1)[1]

    assert b"failed" in content
    assert b"Transcription failed" in transcript_area
    assert b"<form" not in transcript_area
    assert b"Retry" not in transcript_area


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
