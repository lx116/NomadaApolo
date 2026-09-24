import os
import shutil
import signal
import subprocess
import sys
from urllib.parse import urlparse

from django.conf import settings


WORKER_STOP_TIMEOUT_S = 10.0


def worker_command() -> list[str]:
    return [
        sys.executable, "-m", "celery", "-A", "nomadaapolo", "worker",
        "-l", "info", "--concurrency=1",
    ]


def start_worker(popen=subprocess.Popen):
    return popen(worker_command(), cwd=settings.BASE_DIR, start_new_session=True)


def stop_worker(proc, *, timeout=WORKER_STOP_TIMEOUT_S, killpg=os.killpg,
                getpgid=os.getpgid) -> None:
    try:
        if proc.poll() is not None:
            return
        group = getpgid(proc.pid)
        killpg(group, signal.SIGTERM)
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            killpg(group, signal.SIGKILL)
            proc.wait(timeout=1)
    except Exception:
        return


def worker_already_running(app=None, timeout=1.0) -> bool:
    try:
        from api.queue_monitor import inspect_command

        if app is None:
            from nomadaapolo.celery import app as celery_app

            app = celery_app
        return bool(inspect_command(app, "ping", timeout=timeout))
    except Exception:
        return False


def ensure_broker(write, *, run=subprocess.run, ping=None, which=shutil.which) -> bool:
    broker_url = settings.CELERY_BROKER_URL
    parsed = urlparse(broker_url)
    is_local_redis = parsed.scheme == "redis" and parsed.hostname in ("localhost", "127.0.0.1")
    if not is_local_redis:
        return True

    port = parsed.port or 6379

    if ping is None:
        def ping(url):
            import redis

            return redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1).ping()

    try:
        if ping(broker_url):
            return True
    except Exception:
        pass

    manual = "docker compose up -d redis"
    try:
        has_docker = bool(which("docker"))
    except Exception:
        has_docker = False
    if port != 6379 or not has_docker:
        write(f"Redis is not reachable at {parsed.hostname}:{port}; start it ({manual}).")
        return False

    write("Redis is not reachable, starting it with docker compose ...")
    try:
        result = run(["docker", "compose", "up", "-d", "--wait", "redis"],
                     cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=90)
        if result.returncode == 0 and ping(broker_url):
            return True
    except Exception:
        pass
    write(f"Could not start Redis; run `{manual}` manually.")
    return False
