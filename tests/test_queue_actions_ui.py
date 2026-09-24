import re

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from api.models import Audio, AudioTranscription


def create_audio(owner, title, state="pending"):
    audio = Audio.objects.create(
        owner=owner,
        title=title,
        audio_file=SimpleUploadedFile(f"{title}.opus", b"audio"),
        state=state,
    )
    if state == "transcribed":
        AudioTranscription.objects.create(
            audio=audio,
            raw_content="Transcript",
            state="completed",
        )
    return audio


@pytest.mark.django_db
def test_modal_has_run_queue_button_and_result_region(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Pending audio")

    content = client.get(reverse("audio-list")).content.decode()

    assert 'data-queue-action="recover"' in content
    assert "Run queue now" in content
    assert "data-queue-result" in content
    assert 'data-enqueue-url="/queue/enqueue/"' in content


@pytest.mark.django_db
def test_modal_receives_a_csrf_token(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Pending audio")

    content = client.get(reverse("audio-list")).content.decode()
    match = re.search(r'data-csrf="([^"]+)"', content)

    assert match
    assert match.group(1)


@pytest.mark.django_db
def test_pending_panel_has_requeue_button_and_keeps_existing_copy(client):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Pending audio")

    content = client.get(reverse("audio-detail", args=[audio.pk])).content.decode()

    assert "Re-queue now" in content
    assert "Queued for transcription" in content
    assert "Make sure the Celery worker is running" in content


@pytest.mark.django_db
def test_no_requeue_button_for_other_states(client):
    owner = User.objects.create_user(username="owner")
    for state in ("processing", "transcribed", "failed"):
        audio = create_audio(owner, state.title(), state)

        content = client.get(reverse("audio-detail", args=[audio.pk])).content.decode()

        assert "Re-queue now" not in content
        assert "Run queue now" in content


@pytest.mark.django_db
def test_actions_script_posts_with_csrf_and_refreshes(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Pending audio")

    content = client.get(reverse("audio-list")).content.decode()

    assert "X-CSRFToken" in content
    assert 'method: "POST"' in content
    assert "queue:refresh" in content
    assert "textContent" in content


@pytest.mark.django_db
def test_actions_script_avoids_forbidden_strings(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Pending audio")

    content = client.get(reverse("audio-list")).content.decode()
    scripts = re.findall(r"<script>(.*?)</script>", content, re.DOTALL)
    actions_script = next(script for script in scripts if "data-queue-action" in script)

    for forbidden in (
        "setTimeout",
        "audio-states",
        "/audios/status/",
        "transcribe_pending",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
    ):
        assert forbidden not in actions_script


@pytest.mark.django_db
def test_modal_script_refreshes_on_queue_refresh_event(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Pending audio")

    content = client.get(reverse("audio-list")).content.decode()

    assert 'addEventListener("queue:refresh"' in content


@pytest.mark.django_db
def test_no_button_when_there_are_no_audios(client):
    response = client.get(reverse("audio-list"))

    assert response.status_code == 200
    assert "data-queue-action" not in response.content.decode()
