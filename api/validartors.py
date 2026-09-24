from django.core.exceptions import ValidationError
import os

from transcriptor.audio import SUPPORTED_SUFFIXES


def validate_audio_file(file):

    extension = os.path.splitext(file.name)[1].lower()
    valid_extensions = sorted(SUPPORTED_SUFFIXES)

    if extension not in valid_extensions:
        raise ValidationError(f"The file extension isn't admitted. Please use: {', '.join(valid_extensions)}")

    if not file.content_type.startswith('audio/'):
        raise ValidationError('The file type isn\'t admitted. Please use: audio/mpeg')
