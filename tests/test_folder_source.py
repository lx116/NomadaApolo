import importlib
import os
from pathlib import Path

import pytest
from django.contrib.auth.models import User

from api.models import Audio


@pytest.fixture
def folder_source():
    return importlib.import_module("api.folder_source")


def test_disabled_when_root_unset(folder_source):
    with pytest.raises(folder_source.FolderSourceError, match="Folder source is disabled"):
        folder_source.resolve_source_dir(None, "")


def test_subfolder_resolves(folder_source, tmp_path):
    subfolder = tmp_path / "root" / "nested"
    subfolder.mkdir(parents=True)
    root, target = folder_source.resolve_source_dir(str(tmp_path / "root"), "nested")
    assert (root, target) == ((tmp_path / "root").resolve(), subfolder.resolve())


def test_empty_relative_is_root(folder_source, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    assert folder_source.resolve_source_dir(str(root), "") == (root.resolve(), root.resolve())


@pytest.mark.parametrize("relative", ["../outside", "/etc"])
def test_traversal_rejected(folder_source, tmp_path, relative):
    root = tmp_path / "root"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    with pytest.raises(folder_source.FolderSourceError):
        folder_source.resolve_source_dir(str(root), relative)


def test_absolute_rejected(folder_source, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(folder_source.FolderSourceError):
        folder_source.resolve_source_dir(str(root), "/etc")


def test_missing_dir_rejected(folder_source, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(folder_source.FolderSourceError):
        folder_source.resolve_source_dir(str(root), "missing")


def test_symlinked_dir_escaping_root_rejected(folder_source, tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    os.symlink(outside, root / "escape")
    with pytest.raises(folder_source.FolderSourceError):
        folder_source.resolve_source_dir(str(root), "escape")


def test_discovers_supported_case_insensitive(folder_source, tmp_path):
    (tmp_path / "A.MP3").write_bytes(b"a")
    (tmp_path / "b.opus").write_bytes(b"b")
    files, skipped = folder_source.discover_audio_files(tmp_path, tmp_path, 100)
    assert [path.name for path in files] == ["A.MP3", "b.opus"]
    assert skipped == []


def test_ignores_txt_and_nested_dirs(folder_source, tmp_path):
    (tmp_path / "notes.txt").write_text("notes")
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "hidden.mp3").write_bytes(b"audio")
    assert folder_source.discover_audio_files(tmp_path, tmp_path, 100) == ([], [])


def test_symlink_file_skipped_reported(folder_source, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    inside = root / "inside.mp3"
    outside = tmp_path / "outside.mp3"
    inside.write_bytes(b"inside")
    outside.write_bytes(b"outside")
    os.symlink(inside, root / "inside-link.mp3")
    os.symlink(outside, root / "outside-link.mp3")
    files, skipped = folder_source.discover_audio_files(root, root, 100)
    assert files == [inside]
    assert skipped == [("inside-link.mp3", "symlink"), ("outside-link.mp3", "symlink")]


def test_oversize_skipped_reported(folder_source, tmp_path):
    (tmp_path / "large.mp3").write_bytes(b"12345678901")
    assert folder_source.discover_audio_files(tmp_path, tmp_path, 10) == (
        [], [("large.mp3", "too_large")]
    )


def test_empty_folder(folder_source, tmp_path):
    assert folder_source.discover_audio_files(tmp_path, tmp_path, 100) == ([], [])


@pytest.mark.django_db
def test_import_copies_into_media_source_untouched(folder_source, settings, tmp_path):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"original")
    owner = User.objects.create_user(username="owner")
    imported, skipped = folder_source.import_audio_files([source], tmp_path, owner)
    audio = Audio.objects.get()
    assert (imported, skipped) == (["source.mp3"], [])
    assert (settings.MEDIA_ROOT / audio.audio_file.name).read_bytes() == b"original"
    assert source.read_bytes() == b"original"


@pytest.mark.django_db
def test_source_path_is_resolved_absolute(folder_source, tmp_path):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"audio")
    folder_source.import_audio_files([source], tmp_path, User.objects.create_user(username="owner"))
    assert Audio.objects.get().source_path == str(source.resolve())


@pytest.mark.django_db
def test_duplicate_skipped_even_if_changed(folder_source, tmp_path):
    source = tmp_path / "source.mp3"
    source.write_bytes(b"first")
    owner = User.objects.create_user(username="owner")
    folder_source.import_audio_files([source], tmp_path, owner)
    source.write_bytes(b"changed")
    assert folder_source.import_audio_files([source], tmp_path, owner) == (
        [], [("source.mp3", "already_imported")]
    )
    assert Audio.objects.count() == 1


@pytest.mark.django_db
def test_null_source_path_coexist():
    owner = User.objects.create_user(username="owner")
    Audio.objects.create(owner=owner, title="one", source_path=None)
    Audio.objects.create(owner=owner, title="two", source_path=None)
    assert Audio.objects.count() == 2


def test_migration_reversible():
    migration = importlib.import_module("api.migrations.0002_audio_source_path")
    operation, = migration.Migration.operations
    assert operation.__class__.__name__ == "AddField"
    assert operation.model_name == "audio"
    assert operation.name == "source_path"
    assert operation.field.null and operation.field.unique


def test_settings_default_root_is_project_audio_dir(monkeypatch):
    project_settings = importlib.import_module("nomadaapolo.settings")
    original = os.environ.get("AUDIO_SOURCE_ROOT")
    monkeypatch.delenv("AUDIO_SOURCE_ROOT", raising=False)
    try:
        reloaded = importlib.reload(project_settings)
        assert Path(reloaded.AUDIO_SOURCE_ROOT) == reloaded.BASE_DIR / "audio"
    finally:
        if original is None:
            monkeypatch.delenv("AUDIO_SOURCE_ROOT", raising=False)
        else:
            monkeypatch.setenv("AUDIO_SOURCE_ROOT", original)
        importlib.reload(project_settings)


def test_list_source_folders_root_and_nested(folder_source, tmp_path):
    root = tmp_path / "root"
    (root / "a" / "deep").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "loose.txt").write_text("not a folder")

    assert folder_source.list_source_folders(str(root)) == ["", "a", "a/deep", "b"]


def test_list_source_folders_skips_symlinks_and_hidden(folder_source, tmp_path):
    root = tmp_path / "root"
    visible = root / "visible"
    hidden = root / ".hidden"
    target = tmp_path / "target"
    visible.mkdir(parents=True)
    hidden.mkdir()
    target.mkdir()
    os.symlink(target, root / "linked")

    assert folder_source.list_source_folders(str(root)) == ["", "visible"]


def test_list_source_folders_respects_max_depth_and_max_entries(folder_source, tmp_path):
    root = tmp_path / "root"
    (root / "a" / "deep" / "too-deep").mkdir(parents=True)
    (root / "b").mkdir()
    (root / "c").mkdir()

    assert folder_source.list_source_folders(str(root), max_depth=2) == [
        "", "a", "a/deep", "b", "c"
    ]
    assert folder_source.list_source_folders(str(root), max_entries=1) == [""]
    assert folder_source.list_source_folders(str(root), max_entries=3) == ["", "a", "a/deep"]


def test_list_source_folders_missing_or_unset_root_returns_empty(folder_source, tmp_path):
    assert folder_source.list_source_folders(None) == []
    assert folder_source.list_source_folders("") == []
    assert folder_source.list_source_folders(str(tmp_path / "missing")) == []
