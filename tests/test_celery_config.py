import os
import subprocess
import sys

from nomadaapolo.settings import BASE_DIR


def run_python(code, *, env=None):
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=BASE_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_default_broker_url():
    env = os.environ.copy()
    env.pop("CELERY_BROKER_URL", None)

    result = run_python(
        "from nomadaapolo.settings import CELERY_BROKER_URL; print(CELERY_BROKER_URL)",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "redis://localhost:6379/0"


def test_broker_url_environment_override():
    env = os.environ.copy()
    env["CELERY_BROKER_URL"] = "redis://h:1/2"

    result = run_python(
        "from nomadaapolo.settings import CELERY_BROKER_URL; print(CELERY_BROKER_URL)",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "redis://h:1/2"


def test_django_startup_does_not_load_transcriber():
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "tests.settings_test"
    code = (
        "import django, sys; django.setup(); "
        "import nomadaapolo.urls, api.tasks; "
        "raise SystemExit(1 if {'faster_whisper', 'transcriptor.transcriber'} "
        "& sys.modules.keys() else 0)"
    )

    result = run_python(code, env=env)

    assert result.returncode == 0, result.stderr


def test_celery_has_no_result_backend():
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "tests.settings_test"

    result = run_python(
        "from nomadaapolo import celery_app; print(celery_app.conf.result_backend)",
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "None"
