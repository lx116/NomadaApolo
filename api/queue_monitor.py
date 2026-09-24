import base64
import json
import re
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from time import monotonic

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from kombu.exceptions import OperationalError

from api.models import Audio


QUEUE_NAME = "celery"
QUEUE_CAP = 50
BUCKET_CAP = 20
INSPECT_TIMEOUT_S = 1.0
DEADLINE_S = 1.5
PENDING_GRACE_S = 30
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)


def audio_id_from(value) -> str | None:
    match = UUID_RE.search(str(value))
    if not match:
        return None
    try:
        return str(uuid.UUID(match.group()))
    except (ValueError, AttributeError):
        return None


def decode_message(raw: bytes | str) -> dict:
    try:
        envelope = json.loads(raw)
        headers = envelope.get("headers") or {}
        properties = envelope.get("properties") or {}
        task_id = headers.get("id") or properties.get("correlation_id")
        audio_id = audio_id_from(headers.get("argsrepr"))
        if audio_id is None and properties.get("body_encoding") == "base64":
            body = json.loads(base64.b64decode(envelope["body"]))
            audio_id = audio_id_from(body[0][0] if body and body[0] else None)
        return {
            "task_id": str(task_id) if task_id else None,
            "task": str(headers.get("task") or "unknown"),
            "audio_id": audio_id,
        }
    except Exception:
        return {"task_id": None, "task": "unknown", "audio_id": None}


def broker_location(conn) -> str:
    return f"{conn.hostname}:{conn.port}/{conn.virtual_host}"


def read_queue(client, queue=QUEUE_NAME, cap=QUEUE_CAP) -> dict:
    queued = client.llen(queue)
    raw = client.lrange(queue, -cap, -1)
    messages = [decode_message(item) for item in reversed(raw)]
    return {
        "queue": queue,
        "queued": queued,
        "unacked": client.hlen("unacked"),
        "messages": messages,
        "truncated": max(0, queued - len(raw)),
    }


def read_broker(app) -> dict:
    with app.connection_for_read() as conn:
        if conn.transport.driver_type != "redis":
            return {"supported": False, "transport": conn.transport.driver_type}
        started = monotonic()
        client = conn.default_channel.client
        client.ping()
        latency_ms = int((monotonic() - started) * 1000)
        return {
            "supported": True,
            "transport": "redis",
            "location": broker_location(conn),
            "latency_ms": latency_ms,
            **read_queue(client),
        }


def inspect_command(app, command: str, timeout=INSPECT_TIMEOUT_S) -> dict | None:
    return getattr(app.control.inspect(timeout=timeout), command)()


def default_sources(app=None) -> dict:
    if app is None:
        from nomadaapolo.celery import app

    return {
        "broker": lambda: read_broker(app),
        "ping": lambda: inspect_command(app, "ping"),
        "active": lambda: inspect_command(app, "active"),
        "reserved": lambda: inspect_command(app, "reserved"),
    }


def error_code(exc) -> str:
    if isinstance(exc, (OSError, OperationalError)):
        return "broker_unreachable"
    if exc.__class__.__module__.startswith("redis.exceptions") and exc.__class__.__name__ in {
        "ConnectionError",
        "TimeoutError",
    }:
        return "broker_unreachable"
    return "error"


def run_sources(sources: dict, deadline_s=DEADLINE_S) -> dict:
    pool = ThreadPoolExecutor(max_workers=len(sources) or 1, thread_name_prefix="queue-monitor")
    futures = {name: pool.submit(source) for name, source in sources.items()}
    wait(futures.values(), timeout=deadline_s)
    pool.shutdown(wait=False, cancel_futures=True)
    results = {}
    for name, future in futures.items():
        if not future.done() or future.cancelled():
            results[name] = (False, "timeout")
        elif future.exception() is not None:
            results[name] = (False, error_code(future.exception()))
        else:
            results[name] = (True, future.result())
    return results


def summarize_workers(ping, active, reserved) -> dict:
    def tasks(reply):
        return [
            {
                "worker": worker,
                "task_id": task.get("id"),
                "task": task.get("name") or "unknown",
                "audio_id": audio_id_from(task.get("args")),
            }
            for worker, items in sorted((reply or {}).items())
            for task in (items or [])
        ][:BUCKET_CAP]

    return {
        "online": sorted(ping or {}),
        "active": tasks(active),
        "reserved": tasks(reserved),
    }


def read_audios(now) -> dict:
    counts = dict(Audio.objects.values_list("state").annotate(n=Count("pk")).order_by())
    fields = ("pk", "title", "state", "progress_done", "progress_total", "created_at",
              "updated_at")

    def rows(state, order):
        return list(
            Audio.objects.filter(state=state).order_by(order, "pk").values(*fields)[:BUCKET_CAP]
        )

    pending = rows("pending", "created_at")
    processing = rows("processing", "updated_at")

    return {
        "counts": {state: counts.get(state, 0)
                   for state in ("pending", "processing", "transcribed", "failed")},
        "pending": [
            {"id": str(row["pk"]), "title": row["title"],
             "age_s": int((now - row["updated_at"]).total_seconds())}
            for row in pending
        ],
        "processing": [
            {"id": str(row["pk"]), "title": row["title"],
             "percent": min(100, max(0, int(
                 min(max(row["progress_done"], 0.0), row["progress_total"])
                 * 100 / row["progress_total"]
             ))) if row["progress_done"] is not None and row["progress_total"]
             and row["progress_total"] > 0 else None,
             "heartbeat_age_s": int((now - row["updated_at"]).total_seconds())}
            for row in processing
        ],
        "failed": [
            {"id": str(row["pk"]), "title": row["title"],
             "updated_at": row["updated_at"].isoformat()}
            for row in rows("failed", "-updated_at")
        ],
        "transcribed": [
            {"id": str(row["pk"]), "title": row["title"],
             "updated_at": row["updated_at"].isoformat()}
            for row in rows("transcribed", "-updated_at")
        ],
    }


def attach_titles(broker: dict, workers: dict) -> None:
    items = list(broker.get("messages", []))
    items += list(workers.get("active", [])) + list(workers.get("reserved", []))
    ids = {item.get("audio_id") for item in items if item.get("audio_id")}
    try:
        titles = {
            str(audio_id): title
            for audio_id, title in Audio.objects.filter(pk__in=ids).values_list("pk", "title")
        }
    except Exception:
        titles = {}
    for item in items:
        item["title"] = titles.get(item.get("audio_id"))


def _ids(items) -> list[str]:
    return list(dict.fromkeys(
        item.get("id") or item.get("audio_id")
        for item in items
        if item.get("id") or item.get("audio_id")
    ))[:BUCKET_CAP]


def diagnose(broker: dict, workers: dict, audios: dict, stale_minutes: int) -> list[dict]:
    findings = []

    def add(code, severity, message, hint=None, audio_ids=()):
        findings.append({"code": code, "severity": severity, "message": message,
                         "hint": hint, "audio_ids": list(audio_ids)[:BUCKET_CAP]})

    broker_ok = broker.get("ok", False)
    broker_known = broker_ok and broker.get("supported", False)
    workers_ok = workers.get("ok", False)
    audios_ok = audios.get("ok", False)
    stale_s = stale_minutes * 60

    if not broker_ok:
        add("broker_unreachable", "error", "Cannot reach the message broker (Redis).",
            "Start Redis: docker compose up -d redis")

    in_worker = set()
    if workers_ok:
        in_worker = set(_ids(workers.get("active", []) + workers.get("reserved", [])))
        if broker_ok and not workers.get("online"):
            fresh = ([row for row in audios.get("processing", [])
                      if row.get("heartbeat_age_s", stale_s + 1) <= stale_s]
                     if audios_ok else [])
            backlog = ((broker_known and (broker.get("queued", 0) > 0 or broker.get("unacked", 0) > 0))
                       or (audios_ok and audios.get("counts", {}).get("pending", 0) > 0))
            if fresh:
                add("worker_no_reply", "warning",
                    "No worker answered, but a transcription reported progress recently; the worker may be busy.",
                    audio_ids=_ids(fresh))
            elif backlog:
                add("worker_offline_with_backlog", "error",
                    "No worker is running and work is waiting.",
                    'Restart "python manage.py runserver" (it starts the worker), or run: '
                    "celery -A nomadaapolo worker -l info --concurrency=1")

    if (audios_ok and broker_known and workers_ok and broker.get("truncated", 0) == 0
            and (workers.get("online") or broker.get("unacked", 0) == 0)):
        accounted = set(_ids(broker.get("messages", []))) | in_worker
        orphans = [row for row in audios.get("pending", [])
                   if row.get("id") not in accounted and row.get("age_s", 0) >= PENDING_GRACE_S]
        if orphans:
            add("pending_not_queued", "warning", "Pending audios are not in the queue.",
                "python manage.py transcribe_pending --enqueue", _ids(orphans))

    if audios_ok and workers_ok:
        active_ids = set(_ids(workers.get("active", [])))
        stale = [row for row in audios.get("processing", [])
                 if row.get("heartbeat_age_s", 0) > stale_s and row.get("id") not in active_ids]
        if stale:
            add("processing_no_worker", "warning", "Processing audios have no recent progress.",
                f"python manage.py transcribe_pending --reset-stale {stale_minutes}", _ids(stale))

    if (audios_ok and (broker_known or workers_ok)
            and audios.get("counts", {}).get("pending", 0) <= BUCKET_CAP):
        pending_ids = set(_ids(audios.get("pending", [])))
        extra, seen = [], set()
        if broker_known:
            for item in broker.get("messages", []):
                audio_id = item.get("audio_id")
                if audio_id and (audio_id not in pending_ids or audio_id in seen):
                    extra.append(item)
                if audio_id:
                    seen.add(audio_id)
        if workers_ok:
            extra.extend(item for item in workers.get("reserved", [])
                         if item.get("audio_id") and item["audio_id"] not in pending_ids)
        if extra:
            add("queued_not_pending", "info",
                "Queued tasks point to audios that are not pending; the worker will skip them.",
                audio_ids=_ids(extra))

    if broker_known:
        unknown = sum(item.get("task") == "unknown" or item.get("audio_id") is None
                      for item in broker.get("messages", []))
        if unknown:
            noun = "message" if unknown == 1 else "messages"
            add("unknown_message", "info", f"{unknown} queued {noun} could not be decoded.")

    rank = {"error": 0, "warning": 1, "info": 2}
    return sorted(findings, key=lambda item: rank[item["severity"]])


def build_status(sources=None, now=None) -> dict:
    now = now or timezone.now()
    results = run_sources(sources if sources is not None else default_sources())
    ok_b, broker_result = results["broker"]
    broker = {"ok": True, **broker_result} if ok_b else {"ok": False, "error": broker_result}
    if broker.get("location") and "@" in broker["location"]:
        broker["location"] = broker["location"].split("@", 1)[1]
    ping, active, reserved = (results[key] for key in ("ping", "active", "reserved"))
    if ping[0] and active[0] and reserved[0]:
        workers = {"ok": True, **summarize_workers(ping[1], active[1], reserved[1])}
    else:
        workers = {"ok": False, "error": next(value for ok, value in (ping, active, reserved) if not ok)}
    try:
        audios = {"ok": True, **read_audios(now)}
    except Exception:
        audios = {"ok": False, "error": "error"}
    attach_titles(broker, workers)
    return {"generated_at": now.isoformat(),
            "stale_minutes": settings.QUEUE_MONITOR_STALE_MINUTES,
            "broker": broker, "workers": workers, "audios": audios,
            "diagnostics": diagnose(broker, workers, audios,
                                    settings.QUEUE_MONITOR_STALE_MINUTES)}
