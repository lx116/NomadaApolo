from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from api import queue_monitor
from api.folder_source import (
    FolderSourceError,
    discover_audio_files,
    import_audio_files,
    list_source_folders,
    resolve_source_dir,
)
from api.forms import AudioUploadForm
from api.local_owner import get_local_owner
from api.models import Audio
from api.tasks import enqueue_transcription


def progress_payload(state, done, total):
    if state != "processing" or done is None or not total or total <= 0:
        return None
    done = min(max(done, 0.0), total)
    return {
        "done": done,
        "total": total,
        "percent": min(100, max(0, int(done * 100 / total))),
    }


def format_clock(seconds):
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    return (
        f"{hours}:{minutes:02d}:{secs:02d}"
        if hours
        else f"{minutes:02d}:{secs:02d}"
    )


def audio_list(request, pk=None) -> HttpResponse:
    audios = list(
        Audio.objects.select_related("transcription").order_by("-created_at")
    )
    if pk:
        selected = next((audio for audio in audios if audio.pk == pk), None)
        if selected is None:
            raise Http404
    else:
        selected = audios[0] if audios else None
    audio_states = {str(audio.pk): audio.state for audio in audios}
    for audio in audios:
        audio.progress = progress_payload(
            audio.state, audio.progress_done, audio.progress_total
        )
        if audio.progress:
            audio.progress_label = (
                f"{audio.progress['percent']}% – "
                f"{format_clock(audio.progress['done'])} of "
                f"{format_clock(audio.progress['total'])}"
            )
    polling = any(
        state in ("pending", "processing") for state in audio_states.values()
    )
    folder_source_enabled = bool(settings.AUDIO_SOURCE_ROOT)
    source_root_name = (
        Path(settings.AUDIO_SOURCE_ROOT).name if folder_source_enabled else ""
    )
    source_folder_values = (
        list_source_folders(settings.AUDIO_SOURCE_ROOT)
        if folder_source_enabled
        else []
    )
    source_root_missing = folder_source_enabled and not source_folder_values
    source_folders = [
        (
            relative,
            f"{source_root_name}/{relative}"
            if relative
            else f"{source_root_name} (root)",
        )
        for relative in source_folder_values
    ]

    try:
        transcription = selected.transcription if selected else None
    except ObjectDoesNotExist:
        transcription = None

    return render(
        request,
        "audio/list.html",
        {
            "audios": audios,
            "audio_states": audio_states,
            "polling": polling,
            "selected": selected,
            "transcription": transcription,
            "folder_source_enabled": folder_source_enabled,
            "source_folders": source_folders,
            "source_root_name": source_root_name,
            "source_root_missing": source_root_missing,
        },
    )


@require_GET
def audio_status(request) -> JsonResponse:
    audios = [
        {
            "id": str(pk),
            "state": state,
            "progress": progress_payload(state, done, total),
        }
        for pk, state, done, total in Audio.objects.order_by(
            "-created_at"
        ).values_list(
            "pk", "state", "progress_done", "progress_total"
        )
    ]
    return JsonResponse({"audios": audios})


@require_GET
def queue_status(request) -> JsonResponse:
    return JsonResponse(queue_monitor.build_status())


def audio_upload(request) -> HttpResponse:
    form = (
        AudioUploadForm(request.POST, request.FILES)
        if request.method == "POST"
        else AudioUploadForm()
    )
    if request.method == "POST" and form.is_valid():
        audio_file = form.cleaned_data["audio_file"]
        title = form.cleaned_data["title"] or Path(audio_file.name).stem[:200]
        audio = Audio.objects.create(
            owner=get_local_owner(),
            title=title,
            audio_file=audio_file,
        )
        enqueue_transcription(audio)
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
