import base64
import copy
import json
import time
import uuid
from datetime import timedelta

import pytest
from celery import Celery
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from kombu import Connection

from api.models import Audio
from api.queue_monitor import (
    attach_titles,
    audio_id_from,
    broker_location,
    decode_message,
    read_audios,
    read_broker,
    read_queue,
    run_sources,
    summarize_workers,
)


def make_message(audio_id=None, task_id=None, argsrepr=True):
    task_id = str(task_id or uuid.uuid4())
    headers = {"task": "api.tasks.transcribe_audio_task", "id": task_id}
    if argsrepr:
        headers["argsrepr"] = repr((str(audio_id),))
    body = base64.b64encode(json.dumps([[str(audio_id)], {}, {}]).encode()).decode()
    return json.dumps({"body": body, "headers": headers,
                       "properties": {"correlation_id": task_id, "body_encoding": "base64"}}).encode()


class FakeRedis:
    def __init__(self, items=(), unacked=0):
        self.items = list(items)
        self.unacked = unacked

    def llen(self, key):
        return len(self.items)

    def lrange(self, key, start, stop):
        size = len(self.items)
        start = max(0, size + start) if start < 0 else start
        stop = size + stop if stop < 0 else stop
        return self.items[start:stop + 1]

    def hlen(self, key):
        return self.unacked

    def ping(self):
        return True

    def __getattr__(self, name):
        raise AttributeError(name)


def create_audio(owner, title, state="pending"):
    return Audio.objects.create(owner=owner, title=title, state=state,
                                audio_file=SimpleUploadedFile(f"{title}.opus", b"audio"))


def test_audio_id_from_extracts_and_normalizes_first_uuid():
    first, second = uuid.uuid4(), uuid.uuid4()
    assert audio_id_from(f"before {str(first).upper()} after {second}") == str(first)
    assert audio_id_from("nothing") is None


def test_decode_message_from_headers():
    audio_id, task_id = uuid.uuid4(), uuid.uuid4()
    assert decode_message(make_message(audio_id, task_id)) == {
        "task_id": str(task_id), "task": "api.tasks.transcribe_audio_task", "audio_id": str(audio_id)}


def test_decode_message_falls_back_to_base64_body():
    audio_id = uuid.uuid4()
    assert decode_message(make_message(audio_id, argsrepr=False))["audio_id"] == str(audio_id)


def test_decode_message_garbage_never_raises():
    assert decode_message(b"not-json") == {"task_id": None, "task": "unknown", "audio_id": None}


def test_read_queue_lists_next_to_run_first_with_counts():
    ids = [uuid.uuid4() for _ in range(3)]
    result = read_queue(FakeRedis([make_message(i) for i in ids], 2))
    assert [m["audio_id"] for m in result["messages"]] == [str(i) for i in reversed(ids)]
    assert (result["queued"], result["unacked"], result["truncated"]) == (3, 2, 0)


def test_read_queue_caps_oldest_fifty_and_reports_truncated():
    ids = [uuid.uuid4() for _ in range(60)]
    result = read_queue(FakeRedis([make_message(i) for i in ids]))
    assert len(result["messages"]) == 50
    assert result["messages"][0]["audio_id"] == str(ids[-1])
    assert result["truncated"] == 10


def test_read_queue_is_read_only():
    client = FakeRedis([make_message(uuid.uuid4())], 1)
    before = copy.deepcopy(client.__dict__)
    read_queue(client)
    assert client.__dict__ == before


def test_read_broker_memory_transport_is_unsupported():
    assert read_broker(Celery(broker="memory://")) == {"supported": False, "transport": "memory"}


def test_broker_location_omits_credentials():
    location = broker_location(Connection("redis://user:secret@h:6380/2"))
    assert location == "h:6380/2"
    assert "user" not in location and "secret" not in location


def test_run_sources_isolates_failures():
    result = run_sources({"ok": lambda: 3, "down": lambda: (_ for _ in ()).throw(OSError("secret")),
                          "bad": lambda: (_ for _ in ()).throw(RuntimeError("redis://u:pw@h/0 boom"))})
    assert result == {"ok": (True, 3), "down": (False, "broker_unreachable"), "bad": (False, "error")}
    assert "pw" not in repr(result)


def test_run_sources_times_out_slow_source():
    started = time.monotonic()
    result = run_sources({"slow": lambda: time.sleep(1)}, deadline_s=0.2)
    assert result == {"slow": (False, "timeout")}
    assert time.monotonic() - started < 0.7


def test_summarize_workers_whitelists_fields():
    unsafe = {"args": (str(uuid.uuid4()),), "kwargs": {"token": "x"}, "hostname": "private",
              "delivery_info": {"path": "/private/x"}, "path": "/private/y"}
    active = {"z-worker": [{"id": str(i), "name": "task", **unsafe} for i in range(25)]}
    result = summarize_workers({"z-worker": {}, "a-worker": {}}, active, active)
    assert result["online"] == ["a-worker", "z-worker"]
    assert len(result["active"]) == len(result["reserved"]) == 20
    assert all(set(item) == {"worker", "task_id", "task", "audio_id"} for item in result["active"])
    assert "/private/" not in repr(result)


@pytest.mark.django_db
def test_read_audios_counts_all_states_and_caps_buckets():
    owner = User.objects.create_user(username="owner")
    for i in range(25):
        create_audio(owner, f"Pending {i}")
    result = read_audios(timezone.now())
    assert result["counts"] == {"pending": 25, "processing": 0, "transcribed": 0, "failed": 0}
    assert len(result["pending"]) == 20
    assert [x["title"] for x in result["pending"]] == [f"Pending {i}" for i in range(20)]


@pytest.mark.django_db
def test_read_audios_processing_percent_and_heartbeat():
    owner = User.objects.create_user(username="owner")
    now = timezone.now()
    complete = create_audio(owner, "Half", "processing")
    empty = create_audio(owner, "Unknown", "processing")
    Audio.objects.filter(pk=complete.pk).update(progress_done=45, progress_total=90,
                                                    updated_at=now - timedelta(seconds=5))
    result = read_audios(now)
    by_id = {row["id"]: row for row in result["processing"]}
    assert by_id[str(complete.pk)]["percent"] == 50
    assert by_id[str(complete.pk)]["heartbeat_age_s"] == 5
    assert by_id[str(empty.pk)]["percent"] is None


@pytest.mark.django_db
def test_read_audios_exposes_no_private_fields():
    owner = User.objects.create_user(username="owner")
    for state in ("pending", "processing", "failed", "transcribed"):
        create_audio(owner, f"private-{state}", state)
    result = read_audios(timezone.now())
    assert set(result["pending"][0]) == {"id", "title", "age_s"}
    assert set(result["processing"][0]) == {"id", "title", "percent", "heartbeat_age_s"}
    assert set(result["failed"][0]) == set(result["transcribed"][0]) == {"id", "title", "updated_at"}
    assert ".opus" not in repr(result) and "/private/" not in repr(result)


@pytest.mark.django_db
def test_attach_titles_sets_title_or_none():
    owner = User.objects.create_user(username="owner")
    existing = create_audio(owner, "Known")
    missing = uuid.uuid4()
    broker = {"messages": [{"audio_id": str(existing.pk)}, {"audio_id": str(missing)}]}
    workers = {"active": [{"audio_id": str(existing.pk)}], "reserved": [{"audio_id": None}]}
    attach_titles(broker, workers)
    assert [x["title"] for x in broker["messages"]] == ["Known", None]
    assert workers["active"][0]["title"] == "Known"
    assert workers["reserved"][0]["title"] is None
