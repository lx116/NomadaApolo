import os

import pytest
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from api.models import Audio


def message_text(response):
    return "\n".join(str(message) for message in get_messages(response.wsgi_request))


@pytest.mark.django_db
def test_disabled_message_no_import(client, settings):
    settings.AUDIO_SOURCE_ROOT = None
    response = client.post(reverse("audio-folder-scan"), {"subfolder": ""})
    assert response.status_code == 302
    assert "Folder source is disabled" in message_text(response)
    assert not Audio.objects.exists()


@pytest.mark.django_db
def test_get_405(client):
    assert client.get(reverse("audio-folder-scan")).status_code == 405


@pytest.mark.django_db
def test_csrf_403():
    assert Client(enforce_csrf_checks=True).post(reverse("audio-folder-scan")).status_code == 403


@pytest.mark.django_db
def test_subfolder_import_counts_message(client, settings, tmp_path):
    root = tmp_path / "source"
    subfolder = root / "a"
    subfolder.mkdir(parents=True)
    (subfolder / "one.mp3").write_bytes(b"one")
    (subfolder / "two.opus").write_bytes(b"two")
    settings.AUDIO_SOURCE_ROOT = str(root)
    response = client.post(reverse("audio-folder-scan"), {"subfolder": "a"})
    assert response.status_code == 302
    assert "Imported 2 file(s), skipped 0." in message_text(response)
    assert set(Audio.objects.values_list("state", "owner__username")) == {("pending", "local")}


@pytest.mark.django_db
def test_traversal_rejected_no_absolute_path_in_message(client, settings, tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    settings.AUDIO_SOURCE_ROOT = str(root)
    response = client.post(reverse("audio-folder-scan"), {"subfolder": "../outside"})
    text = message_text(response)
    assert "Invalid source folder" in text
    assert str(tmp_path) not in text
    assert not Audio.objects.exists()


@pytest.mark.django_db
def test_scan_form_shown_only_when_enabled(client, settings, tmp_path):
    settings.AUDIO_SOURCE_ROOT = str(tmp_path)
    content = client.get(reverse("audio-list")).content
    assert reverse("audio-folder-scan").encode() in content
    assert b'name="subfolder"' in content
    settings.AUDIO_SOURCE_ROOT = None
    assert reverse("audio-folder-scan").encode() not in client.get(reverse("audio-list")).content
