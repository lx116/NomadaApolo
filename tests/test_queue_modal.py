import re

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from api.models import Audio


def create_audio(owner, title, state="pending"):
    return Audio.objects.create(
        owner=owner,
        title=title,
        audio_file=SimpleUploadedFile(f"{title}.opus", b"audio"),
        state=state,
    )


def queue_script(content):
    return next(
        script
        for script in re.findall(r"<script>(.*?)</script>", content, re.DOTALL)
        if "queue-dialog" in script
    )


def queue_markup(content):
    start = content.index('<button type="button" id="queue-open"')
    end = content.index("<script>", start)
    return content[start:end]


@pytest.mark.django_db
@pytest.mark.parametrize("page", ["empty", "pending", "transcribed", "detail"])
def test_list_pages_render_queue_button_and_dialog(client, page):
    url = reverse("audio-list")
    if page != "empty":
        owner = User.objects.create_user(username=f"owner-{page}")
        audio = create_audio(
            owner,
            page.title(),
            "pending" if page == "pending" else "transcribed",
        )
        if page == "detail":
            url = reverse("audio-detail", args=[audio.pk])

    content = client.get(url).content.decode()

    assert 'id="queue-open"' in content
    assert 'aria-controls="queue-dialog"' in content
    assert '<dialog id="queue-dialog"' in content
    assert 'aria-labelledby="queue-dialog-title"' in content
    assert f'data-url="{reverse("queue-status")}"' in content
    assert f'href="{reverse("audio-upload")}"' in content


@pytest.mark.django_db
def test_queue_button_has_label_only_no_badge(client):
    content = client.get(reverse("audio-list")).content.decode()
    button = content.split('id="queue-open"', 1)[1].split("</button>", 1)[0]

    assert button.endswith(">Queue")
    assert "badge" not in button.lower()
    assert "<span" not in button


@pytest.mark.django_db
def test_upload_page_has_no_queue_modal(client):
    content = client.get(reverse("audio-upload")).content.decode()

    assert 'id="queue-open"' not in content
    assert 'id="queue-dialog"' not in content


@pytest.mark.django_db
def test_dialog_aria_labelledby_resolves_to_heading_and_has_close_button(client):
    content = client.get(reverse("audio-list")).content.decode()

    assert '<h2 id="queue-dialog-title"' in content
    assert "Transcription queue</h2>" in content
    assert 'data-queue-close aria-label="Close"' in content


@pytest.mark.django_db
def test_modal_script_contract(client):
    script = queue_script(client.get(reverse("audio-list")).content.decode())

    for expected in (
        "showModal()",
        "setInterval(",
        "3000",
        "clearInterval(",
        'addEventListener("close"',
        ".focus()",
        "event.target === dialog",
        "inFlight",
        'cache: "no-store"',
        "textContent",
    ):
        assert expected in script
    assert script.count("fetch(") == 1
    assert script.index("showModal()") < script.index("setInterval(")
    assert "if (dialog.open) return;" in script


@pytest.mark.django_db
def test_modal_has_no_html_injection_sinks(client):
    script = queue_script(client.get(reverse("audio-list")).content.decode())

    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in script


@pytest.mark.django_db
def test_modal_script_and_markup_exclude_audio_poller_strings(client):
    content = client.get(reverse("audio-list")).content.decode()
    modal = queue_markup(content) + queue_script(content)

    for forbidden in (
        "setTimeout",
        "audio-states",
        "/audios/status/",
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "transcribe_pending",
        "sessionStorage",
        "location.reload",
    ):
        assert forbidden not in modal


@pytest.mark.django_db
def test_transcribed_only_page_still_has_no_audio_poller(client):
    owner = User.objects.create_user(username="owner")
    create_audio(owner, "Done", "transcribed")
    content = client.get(reverse("audio-list")).content.decode()

    assert "audio-states" not in content
    assert "setTimeout" not in content
    assert "/audios/status/" not in content


@pytest.mark.django_db
def test_modal_contract_strings(client):
    content = client.get(reverse("audio-list")).content.decode()

    for expected in (
        "No issues found",
        "Queue is empty",
        "No running or reserved tasks",
        "No pending audios",
        "No processing audios",
        "No failed audios",
        "No transcribed audios",
        "Broker: ",
        "Worker: ",
        "unreachable",
        "not supported",
        "no reply",
        "Could not load queue status",
    ):
        assert expected in content


@pytest.mark.django_db
@pytest.mark.parametrize("active", [False, True])
def test_list_render_does_not_probe_sources(client, monkeypatch, active):
    def fail(*args, **kwargs):
        raise AssertionError("queue source was probed during page render")

    monkeypatch.setattr("api.queue_monitor.default_sources", fail)
    monkeypatch.setattr("api.queue_monitor.read_broker", fail)
    if active:
        owner = User.objects.create_user(username="owner")
        create_audio(owner, "Pending", "pending")

    assert client.get(reverse("audio-list")).status_code == 200
