from pathlib import Path

from django.contrib import messages
from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

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
