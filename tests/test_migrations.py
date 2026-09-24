import importlib
from uuid import uuid4

import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import migrations

from api.models import Audio


def test_migration_0003_shape():
    module = importlib.import_module("api.migrations.0003_audio_progress")
    assert module.Migration.dependencies == [("api", "0002_audio_source_path")]
    assert len(module.Migration.operations) == 2
    assert all(isinstance(op, migrations.AddField) for op in module.Migration.operations)
    assert {op.name for op in module.Migration.operations} == {
        "progress_done", "progress_total"
    }
    for operation in module.Migration.operations:
        assert operation.model_name == "audio"
        assert operation.field.null is True
        assert operation.reversible is True


@pytest.mark.django_db
def test_audio_progress_defaults_to_none():
    owner = User.objects.create_user(username=f"owner-{uuid4()}")
    audio = Audio.objects.create(
        owner=owner,
        audio_file=SimpleUploadedFile("recording.opus", b"audio"),
    )
    assert (audio.progress_done, audio.progress_total) == (None, None)
