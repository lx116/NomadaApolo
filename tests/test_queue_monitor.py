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
from django.urls import reverse
from django.utils import timezone
from kombu import Connection

from api.models import Audio, AudioTranscription
from api.queue_monitor import (
    attach_titles,
    audio_id_from,
    build_status,
    broker_location,
    decode_message,
    diagnose,
    read_audios,
    read_broker,
    read_queue,
    run_sources,
    summarize_workers,
)


NOW = timezone.now()


def broker(messages=(), queued=None, unacked=0, truncated=0):
    return {"ok": True, "supported": True, "transport": "redis", "location": "localhost:6379/0",
            "latency_ms": 1, "queue": "celery", "queued": len(messages) if queued is None else queued,
            "unacked": unacked, "truncated": truncated, "messages": list(messages)}


def workers(online=("worker",), active=(), reserved=()):
    return {"ok": True, "online": list(online), "active": list(active), "reserved": list(reserved)}


def audios(pending=(), processing=(), transcribed=(), failed=(), pending_count=None):
    return {"ok": True, "counts": {"pending": len(pending) if pending_count is None else pending_count,
            "processing": len(processing), "transcribed": len(transcribed), "failed": len(failed)},
            "pending": list(pending), "processing": list(processing), "transcribed": list(transcribed),
            "failed": list(failed)}


def codes(b=None, w=None, a=None, stale=10):
    return [item["code"] for item in diagnose(b or broker(), w or workers(), a or audios(), stale)]


def sources(b=None, ping=None, active=None, reserved=None):
    values = {"broker": b or broker(), "ping": {"worker": {} } if ping is None else ping,
              "active": {"worker": []} if active is None else active,
              "reserved": {"worker": []} if reserved is None else reserved}
    return {key: (lambda value=value: value) for key, value in values.items()}


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


def test_broker_unreachable_suppresses_worker_and_queue_diagnostics():
    b = {"ok": False, "error": "broker_unreachable"}
    assert codes(b, workers(online=()), audios(pending=[{"id": "p", "age_s": 60}])) == ["broker_unreachable"]


def test_worker_offline_with_backlog():
    assert "worker_offline_with_backlog" in codes(
        broker([{"audio_id": "p", "task": "task"}]), workers(online=()))


def test_worker_no_reply_when_heartbeat_recent():
    a = audios(processing=[{"id": "p", "heartbeat_age_s": 30}])
    result = codes(broker([{"audio_id": "p", "task": "task"}]), workers(online=()), a)
    assert "worker_no_reply" in result and "worker_offline_with_backlog" not in result


def test_offline_but_idle_has_no_diagnostics():
    assert codes(w=workers(online=())) == []


def test_pending_not_queued_hint_enqueue():
    result = diagnose(broker(), workers(), audios(pending=[{"id": "p", "age_s": 31}]), 10)
    assert result[0]["code"] == "pending_not_queued" and "--enqueue" in result[0]["hint"]


def test_pending_not_queued_respects_grace_period():
    assert codes(a=audios(pending=[{"id": "p", "age_s": 29}])) == []


def test_reserved_audio_is_not_pending_orphan():
    item = {"audio_id": "p", "task": "task"}
    assert codes(w=workers(reserved=[item]), a=audios(pending=[{"id": "p", "age_s": 31}])) == []


@pytest.mark.parametrize("b,w", [
    (broker(queued=51, truncated=1), workers()),
    ({"ok": True, "supported": False, "transport": "memory"}, workers()),
    (broker(unacked=1), {"ok": False, "error": "timeout"}),
])
def test_pending_not_queued_suppressed_when_queue_truncated(b, w):
    assert "pending_not_queued" not in codes(b, w, audios(pending=[{"id": "p", "age_s": 60}]))


def test_processing_no_worker_hint_reset_stale():
    result = diagnose(broker(), workers(), audios(processing=[{"id": "p", "heartbeat_age_s": 601}]), 10)
    assert result[0]["code"] == "processing_no_worker" and "--reset-stale 10" in result[0]["hint"]


@pytest.mark.django_db
def test_processing_threshold_boundary_uses_setting(settings):
    owner = User.objects.create_user(username="owner")
    old = create_audio(owner, "Old", "processing")
    recent = create_audio(owner, "Recent", "processing")
    Audio.objects.filter(pk=old.pk).update(updated_at=NOW - timedelta(minutes=11))
    Audio.objects.filter(pk=recent.pk).update(updated_at=NOW - timedelta(minutes=9))
    settings.QUEUE_MONITOR_STALE_MINUTES = 10
    first = build_status(sources(), NOW)["diagnostics"]
    settings.QUEUE_MONITOR_STALE_MINUTES = 5
    second = build_status(sources(), NOW)["diagnostics"]
    assert next(x for x in first if x["code"] == "processing_no_worker")["audio_ids"] == [str(old.pk)]
    assert next(x for x in second if x["code"] == "processing_no_worker")["audio_ids"] == [str(old.pk), str(recent.pk)]


def test_processing_listed_active_is_not_stale():
    assert codes(w=workers(active=[{"audio_id": "p"}]), a=audios(processing=[{"id": "p", "heartbeat_age_s": 1800}])) == []


def test_queued_not_pending_covers_transcribed_missing_and_duplicate():
    messages = [{"audio_id": "p", "task": "task"}, {"audio_id": "p", "task": "task"},
                {"audio_id": "done", "task": "task"}, {"audio_id": "missing", "task": "task"}]
    result = diagnose(broker(messages), workers(), audios(pending=[{"id": "p", "age_s": 60}],
                      transcribed=[{"id": "done"}]), 10)
    assert [x["code"] for x in result] == ["queued_not_pending"]
    assert result[0]["audio_ids"] == ["p", "done", "missing"]


def test_queued_not_pending_skipped_when_pending_over_cap():
    assert codes(broker([{"audio_id": "x", "task": "task"}]), workers(), audios(pending_count=21)) == []


def test_unknown_message_single_info_with_count():
    result = diagnose(broker([{"audio_id": None, "task": "unknown"}] * 2), workers(), audios(), 10)
    assert len(result) == 1 and result[0]["code"] == "unknown_message" and "2" in result[0]["message"]


def test_healthy_state_has_no_diagnostics():
    assert codes(a=audios(transcribed=[{"id": "done"}])) == []


def test_diagnostics_ordered_error_warning_info():
    b = broker([{"audio_id": None, "task": "unknown"}])
    a = audios(pending=[{"id": "p", "age_s": 60}])
    assert [x["severity"] for x in diagnose(b, workers(online=()), a, 10)] == ["error", "warning", "info"]


@pytest.mark.django_db
def test_build_status_payload_keys_titles_and_caps(settings):
    settings.QUEUE_MONITOR_STALE_MINUTES = 10
    owner = User.objects.create_user(username="owner")
    known = create_audio(owner, "Known")
    message = {"task_id": "t", "task": "task", "audio_id": str(known.pk)}
    result = build_status(sources(broker([message])), now=NOW)
    assert set(result) == {"generated_at", "stale_minutes", "broker", "workers", "audios", "diagnostics"}
    assert result["generated_at"] == NOW.isoformat() and result["broker"]["messages"][0]["title"] == "Known"


@pytest.mark.django_db
def test_one_source_failing_keeps_others():
    fakes = sources()
    fakes["active"] = lambda: (_ for _ in ()).throw(RuntimeError("secret"))
    result = build_status(fakes, NOW)
    assert result["broker"]["ok"] and not result["workers"]["ok"] and result["audios"]["ok"]


@pytest.mark.django_db
def test_all_sources_failing_still_valid_payload(monkeypatch):
    fail = lambda: (_ for _ in ()).throw(RuntimeError("secret"))
    monkeypatch.setattr("api.queue_monitor.read_audios", fail)
    result = build_status({key: fail for key in ("broker", "ping", "active", "reserved")}, NOW)
    assert not result["broker"]["ok"] and not result["workers"]["ok"] and not result["audios"]["ok"]


@pytest.mark.django_db
def test_error_text_hygiene():
    fail = lambda: (_ for _ in ()).throw(RuntimeError("redis://u:pw@h/0 boom /private/x"))
    assert "pw" not in json.dumps(build_status({key: fail for key in ("broker", "ping", "active", "reserved")}, NOW))


@pytest.mark.django_db
def test_queue_status_view_200_json_and_reverse(client, monkeypatch):
    monkeypatch.setattr("api.queue_monitor.default_sources", lambda app=None: sources())
    assert reverse("queue-status") == "/queue/status/"
    response = client.get(reverse("queue-status"))
    assert response.status_code == 200 and response.headers["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_queue_status_all_sources_failing_returns_200(client, monkeypatch):
    fail = lambda: (_ for _ in ()).throw(RuntimeError())
    monkeypatch.setattr("api.queue_monitor.default_sources", lambda app=None: {k: fail for k in ("broker", "ping", "active", "reserved")})
    assert client.get("/queue/status/").status_code == 200


@pytest.mark.django_db
def test_queue_status_rejects_non_get(client):
    assert client.post("/queue/status/").status_code == 405


@pytest.mark.django_db
def test_queue_status_get_writes_nothing(client, monkeypatch):
    owner = User.objects.create_user(username="owner")
    audio = create_audio(owner, "Existing")
    before = (Audio.objects.count(), AudioTranscription.objects.count(), audio.updated_at)
    monkeypatch.setattr("api.queue_monitor.default_sources", lambda app=None: sources())
    client.get("/queue/status/"); client.get("/queue/status/")
    audio.refresh_from_db()
    assert (Audio.objects.count(), AudioTranscription.objects.count(), audio.updated_at) == before


@pytest.mark.django_db
def test_queue_status_privacy_allowlist(client, monkeypatch):
    owner = User.objects.create_user(username="owner")
    audio = Audio.objects.create(owner=owner, title="Allowed title", source_path="/private/secret.opus",
                                 audio_file=SimpleUploadedFile("secret-file.opus", b"x"), state="transcribed")
    AudioTranscription.objects.create(audio=audio, raw_content="TOP SECRET TEXT")
    b = broker(); b["location"] = "redis://u:password@localhost/0"
    monkeypatch.setattr("api.queue_monitor.default_sources", lambda app=None: sources(b))
    content = client.get("/queue/status/").content
    assert b"Allowed title" in content
    assert all(value not in content for value in (b"/private/", b"secret-file.opus", b"TOP SECRET", b"password"))


@pytest.mark.django_db
@pytest.mark.parametrize("active", [False, True])
def test_audio_list_render_does_not_probe_sources(client, monkeypatch, active):
    if active:
        create_audio(User.objects.create_user(username="owner"), "Active")
    monkeypatch.setattr("api.queue_monitor.default_sources", lambda app=None: (_ for _ in ()).throw(AssertionError()))
    assert client.get("/").status_code == 200
