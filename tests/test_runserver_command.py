import io
from unittest.mock import Mock

import pytest
from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunserverCommand
from django.core.management import get_commands

from api.management.commands.runserver import Command


def run_command(
    monkeypatch, *, run_main=None, enabled=True, running=False,
    server_error=None, worker_error=None, worker_exit=None, capture=None,
):
    from api import dev_stack

    if run_main is None:
        monkeypatch.delenv("RUN_MAIN", raising=False)
    else:
        monkeypatch.setenv("RUN_MAIN", run_main)
    proc = Mock(pid=123)
    proc.poll.return_value = worker_exit
    stack = {
        "ensure_broker": Mock(return_value=True),
        "worker_already_running": Mock(return_value=running),
        "start_worker": Mock(return_value=proc),
        "stop_worker": Mock(),
    }
    stack["start_worker"].side_effect = worker_error
    for name, fake in stack.items():
        monkeypatch.setattr(dev_stack, name, fake)
    monkeypatch.setattr("api.management.commands.runserver.time.sleep", Mock())
    server_run = Mock(side_effect=server_error)
    monkeypatch.setattr(StaticRunserverCommand, "run", server_run)
    stream = io.StringIO()
    command = Command(stdout=stream)
    if capture is not None:
        capture.update(proc=proc, stack=stack)
    command.run(start_worker=enabled)
    return proc, stack, server_run, stream


def test_runserver_command_is_ours_and_extends_staticfiles():
    parser = Command().create_parser("manage.py", "runserver")
    assert get_commands()["runserver"] == "api"
    assert issubclass(Command, StaticRunserverCommand)
    assert parser.parse_args(["--nostatic"]).use_static_handler is False


def test_installed_apps_order_puts_api_before_staticfiles():
    api = settings.INSTALLED_APPS.index("api.apps.ApiConfig")
    assert api < settings.INSTALLED_APPS.index("django.contrib.staticfiles")


def test_no_worker_flag_sets_start_worker_false():
    parser = Command().create_parser("manage.py", "runserver")
    assert parser.parse_args([]).start_worker is True
    assert parser.parse_args(["--no-worker"]).start_worker is False


def test_run_starts_worker_in_parent_process(monkeypatch):
    proc, stack, server_run, _ = run_command(monkeypatch)
    stack["ensure_broker"].assert_called_once()
    stack["start_worker"].assert_called_once_with()
    server_run.assert_called_once()
    stack["stop_worker"].assert_called_once_with(proc)


def test_run_does_not_start_worker_in_reloader_child(monkeypatch):
    _, stack, server_run, _ = run_command(monkeypatch, run_main="true")
    stack["ensure_broker"].assert_not_called()
    stack["start_worker"].assert_not_called()
    server_run.assert_called_once()


def test_run_skips_worker_when_disabled(monkeypatch):
    _, stack, server_run, _ = run_command(monkeypatch, enabled=False)
    stack["ensure_broker"].assert_not_called()
    stack["start_worker"].assert_not_called()
    server_run.assert_called_once()


def test_run_skips_worker_when_one_is_already_running(monkeypatch):
    _, stack, _, stream = run_command(monkeypatch, running=True)
    stack["worker_already_running"].assert_called_once_with()
    stack["start_worker"].assert_not_called()
    assert "already running" in stream.getvalue()


@pytest.mark.parametrize("error", [KeyboardInterrupt(), RuntimeError("server failed")])
def test_run_stops_worker_even_if_server_raises(monkeypatch, error):
    capture = {}
    with pytest.raises(type(error)):
        run_command(monkeypatch, server_error=error, capture=capture)
    capture["stack"]["stop_worker"].assert_called_once_with(capture["proc"])


def test_run_reports_worker_that_exits_immediately(monkeypatch):
    _, stack, server_run, stream = run_command(monkeypatch, worker_exit=1)
    assert "exit code 1" in stream.getvalue()
    assert "celery -A nomadaapolo worker" in stream.getvalue()
    stack["stop_worker"].assert_not_called()
    server_run.assert_called_once()


def test_run_survives_worker_start_failure(monkeypatch):
    _, _, server_run, stream = run_command(monkeypatch, worker_error=OSError("cannot start"))
    assert "cannot start" in stream.getvalue()
    server_run.assert_called_once()
