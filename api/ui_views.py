from django.core.exceptions import ObjectDoesNotExist
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

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
