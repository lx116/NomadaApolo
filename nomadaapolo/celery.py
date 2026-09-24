import os

from celery import Celery


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "nomadaapolo.settings")

app = Celery("nomadaapolo")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
