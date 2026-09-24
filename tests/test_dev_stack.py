import signal
import subprocess
import sys
from unittest.mock import Mock, call

import pytest
from django.conf import settings

from api import dev_stack


def fake_proc(*, poll=None, wait=None):
    proc = Mock(pid=12)
    proc.poll.return_value = poll
    proc.wait.side_effect = wait
    return proc


@pytest.fixture(autouse=True)
def local_broker(settings):
    settings.CELERY_BROKER_URL = "redis://localhost:6379/0"


def test_worker_command_uses_current_interpreter_and_module():
    assert dev_stack.worker_command() == [
        sys.executable, "-m", "celery", "-A", "nomadaapolo", "worker", "-l",
        "info", "--concurrency=1",
    ]


def test_start_worker_uses_new_session_and_project_cwd():
    popen = Mock(return_value="proc")
    assert dev_stack.start_worker(popen=popen) == "proc"
    popen.assert_called_once_with(
        dev_stack.worker_command(), cwd=settings.BASE_DIR, start_new_session=True)


def test_stop_worker_terminates_group_then_waits():
    proc, killpg = fake_proc(), Mock()
    dev_stack.stop_worker(proc, timeout=3, getpgid=lambda pid: 42, killpg=killpg)
    killpg.assert_called_once_with(42, signal.SIGTERM)
    proc.wait.assert_called_once_with(timeout=3)


def test_stop_worker_kills_group_after_timeout():
    proc = fake_proc(wait=[subprocess.TimeoutExpired("worker", 3), None])
    killpg = Mock()
    dev_stack.stop_worker(proc, timeout=3, getpgid=lambda pid: 42, killpg=killpg)
    assert killpg.call_args_list == [call(42, signal.SIGTERM), call(42, signal.SIGKILL)]
    assert proc.wait.call_args_list == [call(timeout=3), call(timeout=1)]


def test_stop_worker_noop_when_already_exited():
    proc, killpg = fake_proc(poll=0), Mock()
    dev_stack.stop_worker(proc, killpg=killpg, getpgid=Mock())
    killpg.assert_not_called()


def test_stop_worker_never_raises():
    dev_stack.stop_worker(fake_proc(), getpgid=lambda pid: 42,
                          killpg=Mock(side_effect=ProcessLookupError))


def test_worker_already_running_true_and_false(monkeypatch):
    import api.queue_monitor

    inspect = Mock(side_effect=({"w": {}}, {}, None, RuntimeError()))
    monkeypatch.setattr(api.queue_monitor, "inspect_command", inspect)
    for expected in (True, False, False, False):
        assert dev_stack.worker_already_running(app=object()) is expected


def test_ensure_broker_reachable_does_nothing():
    run = Mock()
    assert dev_stack.ensure_broker(Mock(), ping=lambda url: True, run=run) is True
    run.assert_not_called()


def test_ensure_broker_starts_redis_with_docker_when_local_and_unreachable():
    run = Mock(return_value=subprocess.CompletedProcess([], 0))
    assert dev_stack.ensure_broker(
        Mock(), ping=Mock(side_effect=(False, True)),
        which=lambda name: "/usr/bin/docker", run=run) is True
    run.assert_called_once_with(
        ["docker", "compose", "up", "-d", "--wait", "redis"],
        cwd=settings.BASE_DIR, capture_output=True, text=True, timeout=90,
    )


def test_ensure_broker_skips_non_local_or_non_redis_broker(settings):
    for url in ("redis://cache.example.com:6379/0", "memory://"):
        settings.CELERY_BROKER_URL = url
        ping, run = Mock(), Mock()
        assert dev_stack.ensure_broker(Mock(), ping=ping, run=run) is True
        ping.assert_not_called()
        run.assert_not_called()


def test_ensure_broker_warns_without_docker():
    write, run = Mock(), Mock()
    assert dev_stack.ensure_broker(
        write, ping=lambda url: False, which=lambda name: None, run=run
    ) is False
    write.assert_called_once()
    run.assert_not_called()


def test_ensure_broker_never_raises_when_docker_fails():
    failures = [subprocess.TimeoutExpired("docker", 90), subprocess.CompletedProcess([], 1)]
    for failure in failures:
        write = Mock()
        run = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
        assert dev_stack.ensure_broker(
            write, ping=lambda url: False,
            which=lambda name: "/usr/bin/docker", run=run,
        ) is False
        assert write.call_count == 2


def test_ensure_broker_does_not_leak_credentials(settings):
    settings.CELERY_BROKER_URL = "redis://user:secret@localhost:6379/0"
    messages = []
    dev_stack.ensure_broker(messages.append, ping=lambda url: False, which=lambda name: None)
    assert all("secret" not in message for message in messages)
