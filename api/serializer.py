from rest_framework import serializers
from .models import Audio
from .validartors import validate_audio_file


class AudioSerializer(serializers.ModelSerializer):

    audio_file = serializers.FileField(validators=[validate_audio_file])

    class Meta:
        model = Audio
        fields = '__all__'