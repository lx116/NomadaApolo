from django.db import models
from django.contrib.auth.models import User

import uuid


class Audio(models.Model):
    STATE_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('transcribed', 'Transcribed'),
        ('failed', 'Failed'),
    ]

    identifier = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='audios'
    )

    title = models.CharField(max_length=200)

    audio_file = models.FileField(
        upload_to='audio/'
    )

    source_path = models.CharField(
        max_length=4096,
        null=True,
        blank=True,
        unique=True,
        editable=False,
    )

    state = models.CharField(
        max_length=20,
        choices=STATE_CHOICES,
        default='pending'
    )

    progress_done = models.FloatField(null=True, blank=True, editable=False)
    progress_total = models.FloatField(null=True, blank=True, editable=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class AudioTranscription(models.Model):
    STATE_CHOICES = [
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ]

    identifier = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    audio = models.OneToOneField(
        Audio,
        on_delete=models.CASCADE,
        related_name='transcription'
    )

    raw_content = models.TextField(
        blank=True
    )

    language = models.CharField(
        max_length=10,
        blank=True,
        null=True
    )

    state = models.CharField(
        max_length=20,
        choices=STATE_CHOICES,
        default='pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Transcription - {self.audio.title}"


class TranscriptionContent(models.Model):
    CONTENT_TYPE_CHOICES = [
        ('clean', 'Clean transcription'),
        ('summary', 'Summary'),
        ('notes', 'Notes'),
        ('article', 'Article'),
        ('interview', 'Interview'),
        ('custom', 'Custom'),
    ]

    identifier = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )

    transcription = models.ForeignKey(
        AudioTranscription,
        on_delete=models.CASCADE,
        related_name='contents'
    )

    content_type = models.CharField(
        max_length=30,
        choices=CONTENT_TYPE_CHOICES
    )

    title = models.CharField(
        max_length=200,
        blank=True
    )

    content = models.TextField()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.content_type} - {self.transcription.audio.title}"
