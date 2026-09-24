import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _docker_compose():
    if shutil.which("docker") is None:
        pytest.skip("docker is unavailable")
    version = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, text=True
    )
    if version.returncode:
        pytest.skip("docker compose is unavailable")


def test_compose_config():
    _docker_compose()
    check = subprocess.run(
        ["docker", "compose", "config", "-q"], cwd=ROOT, capture_output=True
    )
    assert check.returncode == 0
    rendered = subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    config = json.loads(rendered.stdout)
    assert set(config["services"]) == {"redis"}
    redis = config["services"]["redis"]
    assert redis["image"] == "redis:7-alpine"
    assert len(redis["ports"]) == 1
    assert redis["ports"][0]["host_ip"] == "127.0.0.1"
    assert redis["ports"][0]["published"] == "6379"
    assert redis["restart"] == "unless-stopped"
    assert "redis-cli" in redis["healthcheck"]["test"]
    assert "ping" in redis["healthcheck"]["test"]
    assert "volumes" not in redis


def test_readme_background_transcription_runbook():
    readme = (ROOT / "README.md").read_text()
    heading = "## Background transcription (Celery + Redis)"
    section = readme.split(heading, 1)[1].split("\n## ", 1)[0]
    assert "docker compose up -d redis" in section
    assert "docker compose down" in section
    assert "celery -A nomadaapolo worker --concurrency=1" in section
    assert "transcribe_pending --enqueue" in section
    assert "brew" not in section.lower()
