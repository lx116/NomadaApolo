import pytest


@pytest.fixture(autouse=True)
def media_root(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture(autouse=True)
def disable_folder_source(settings):
    settings.AUDIO_SOURCE_ROOT = None
