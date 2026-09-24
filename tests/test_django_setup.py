from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile

from api.models import Audio


@pytest.mark.django_db
def test_audio_file_is_stored_under_media_root():
    owner = User.objects.create_user(username="owner")
    audio = Audio.objects.create(
        owner=owner,
        title="Sample",
        audio_file=SimpleUploadedFile("sample.opus", b"data"),
    )

    stored_path = Path(audio.audio_file.path)
    assert stored_path.is_relative_to(settings.MEDIA_ROOT)
    assert not stored_path.is_relative_to(Path.cwd() / "audio")
