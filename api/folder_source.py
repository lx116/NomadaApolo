import os
from pathlib import Path

from django.core.files import File
from django.db import IntegrityError, transaction

from api.models import Audio
from transcriptor.audio import SUPPORTED_SUFFIXES


class FolderSourceError(Exception):
    pass


def list_source_folders(
    root: str | None, max_depth: int = 3, max_entries: int = 200
) -> list[str]:
    if not root or max_entries <= 0:
        return []
    try:
        if not os.path.isdir(root):
            return []
    except OSError:
        return []

    folders = [""]
    if len(folders) >= max_entries:
        return folders
    try:
        for current, dirnames, _filenames in os.walk(
            root, topdown=True, followlinks=False
        ):
            relative = Path(current).relative_to(root)
            depth = len(relative.parts)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if not name.startswith(".")
                and not os.path.islink(os.path.join(current, name))
            )
            if depth >= max_depth:
                dirnames[:] = []
            if depth and depth <= max_depth:
                folders.append(relative.as_posix())
                if len(folders) >= max_entries:
                    break
    except (OSError, ValueError):
        pass
    return folders


def resolve_source_dir(root: str | None, relative: str) -> tuple[Path, Path]:
    if not root:
        raise FolderSourceError("Folder source is disabled")
    try:
        relative_path = Path(relative)
        if "\x00" in relative or relative_path.is_absolute():
            raise ValueError
        root_resolved = Path(root).resolve(strict=True)
        target = (root_resolved / relative_path).resolve(strict=True)
        if not root_resolved.is_dir() or not target.is_dir():
            raise ValueError
        if not target.is_relative_to(root_resolved):
            raise ValueError
    except (OSError, ValueError, RuntimeError) as error:
        raise FolderSourceError("Invalid source folder") from error
    return root_resolved, target


def discover_audio_files(
    directory: Path, root: Path, max_bytes: int
) -> tuple[list[Path], list[tuple[str, str]]]:
    files = []
    skipped = []
    try:
        entries = sorted(os.scandir(directory), key=lambda entry: entry.name)
        for entry in entries:
            name = (directory / entry.name).relative_to(root).as_posix()
            if entry.is_symlink():
                skipped.append((name, "symlink"))
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            path = Path(entry.path)
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                continue
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                continue
            if entry.stat(follow_symlinks=False).st_size > max_bytes:
                skipped.append((name, "too_large"))
                continue
            files.append(resolved)
    except (OSError, ValueError, RuntimeError) as error:
        raise FolderSourceError("Unable to scan source folder") from error
    return files, skipped


def import_audio_files(
    paths: list[Path], root: Path, owner
) -> tuple[list[str], list[tuple[str, str]]]:
    imported = []
    skipped = []
    for path in paths:
        resolved = path.resolve(strict=True)
        name = resolved.relative_to(root).as_posix()
        source_path = str(resolved)
        if Audio.objects.filter(source_path=source_path).exists():
            skipped.append((name, "already_imported"))
            continue
        audio = Audio(owner=owner, title=path.stem[:200], source_path=source_path)
        with resolved.open("rb") as source:
            audio.audio_file.save(path.name, File(source), save=False)
        try:
            with transaction.atomic():
                audio.save()
        except IntegrityError:
            audio.audio_file.delete(save=False)
            skipped.append((name, "already_imported"))
        else:
            imported.append(name)
    return imported, skipped
