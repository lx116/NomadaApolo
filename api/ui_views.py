from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from api.folder_source import (
    FolderSourceError,
    discover_audio_files,
    import_audio_files,
    resolve_source_dir,
)
from api.forms import AudioUploadForm
from api.local_owner import get_local_owner
from api.models import Audio


def audio_list(request, pk=None) -> HttpResponse:
    audios = Audio.objects.select_related("transcription").order_by("-created_at")
    selected = get_object_or_404(audios, pk=pk) if pk else audios.first()

    try:
        transcription = selected.transcription if selected else None
    except ObjectDoesNotExist:
        transcription = None

    return render(
        request,
        "audio/list.html",
        {
            "audios": audios,
            "selected": selected,
            "transcription": transcription,
            "folder_source_enabled": bool(settings.AUDIO_SOURCE_ROOT),
        },
    )


def audio_upload(request) -> HttpResponse:
    form = (
        AudioUploadForm(request.POST, request.FILES)
        if request.method == "POST"
        else AudioUploadForm()
    )
    if request.method == "POST" and form.is_valid():
        audio_file = form.cleaned_data["audio_file"]
        title = form.cleaned_data["title"] or Path(audio_file.name).stem[:200]
        Audio.objects.create(
            owner=get_local_owner(),
            title=title,
            audio_file=audio_file,
        )
        messages.success(request, "Audio uploaded successfully.")
        return redirect("audio-list")

    return render(request, "audio/upload.html", {"form": form})


def _scan_summary(imported: list[str], skipped: list[tuple[str, str]]) -> str:
    summary = f"Imported {len(imported)} file(s), skipped {len(skipped)}."
    return "\n".join([summary, *(f"{name}: {reason}" for name, reason in skipped)])


@require_POST
def audio_folder_scan(request) -> HttpResponse:
    owner = get_local_owner()
    try:
        root, directory = resolve_source_dir(
            settings.AUDIO_SOURCE_ROOT, request.POST.get("subfolder", "")
        )
        paths, skipped = discover_audio_files(
            directory, root, settings.AUDIO_SOURCE_MAX_BYTES
        )
        imported, import_skipped = import_audio_files(paths, root, owner)
        skipped.extend(import_skipped)
    except FolderSourceError as error:
        messages.error(request, str(error))
        return redirect("audio-list")

    if not paths and not skipped:
        messages.info(request, "No audio files found.")
    else:
        level = messages.success if imported else messages.info
        level(request, _scan_summary(imported, skipped))
    return redirect("audio-list")
