from pathlib import Path

from django import forms

from transcriptor.audio import SUPPORTED_SUFFIXES


class AudioUploadForm(forms.Form):
    title = forms.CharField(max_length=200, required=False)
    audio_file = forms.FileField()

    def clean_audio_file(self):
        audio_file = self.cleaned_data["audio_file"]
        if Path(audio_file.name).suffix.lower() not in SUPPORTED_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
            raise forms.ValidationError(
                f"Unsupported audio file. Supported suffixes: {supported}."
            )
        return audio_file
