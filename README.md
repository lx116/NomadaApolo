# NomadaApolo — Transcription Engine

## Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Prerequisites

```bash
brew install ffmpeg   # provides ffmpeg and ffprobe on PATH
```

## Test

```bash
pytest
```

The mocked contract tests run without FFmpeg. The real-binary integration
test is skipped automatically when `ffprobe`/`ffmpeg` are absent.

## Background transcription (Celery + Redis)

Start Redis, inspect it, and stop it when finished:

```bash
docker compose up -d redis
docker compose ps
docker compose logs redis
docker compose down
```

Run Django in Terminal A and the Celery worker in Terminal B:

```bash
python manage.py runserver
celery -A nomadaapolo worker --concurrency=1 -l info
```

Enqueue audio loaded before this change or while the broker was unavailable:

```bash
python manage.py transcribe_pending --enqueue
```

Reset stale processing rows before enqueueing them again:

```bash
python manage.py transcribe_pending --reset-stale 30 --enqueue
```

Set the `CELERY_BROKER_URL` environment variable to override the broker URL.

## Public Contract (Slice 1 + 2)

```python
from transcriptor.audio import validate_audio_input, probe_duration, normalize_audio

path = validate_audio_input("audio.m4a")       # returns pathlib.Path; raises on invalid input
duration = probe_duration(path)                # float seconds, via ffprobe
wav = normalize_audio(path, output_dir="out")  # -> out/audio.16k-mono.wav (16 kHz mono PCM WAV)
```

Supported suffixes (case-insensitive): `.m4a`, `.mp3`, `.wav`, `.mp4`.

- `probe_duration(path) -> float` invokes `ffprobe` with an explicit argv and
  `shell=False`. It raises `RuntimeError("ffprobe not found")` when the binary
  is missing, or `AudioProbeError` (carrying stderr when available) on non-zero
  exit, empty, non-numeric, negative, or non-finite output. The source is never
  modified.
- `normalize_audio(path, output_dir=None) -> Path` invokes `ffmpeg`
  (`-nostdin -y -i <path> -vn -ac 1 -ar 16000 -c:a pcm_s16le`) into a staged
  temp WAV, verifies it is mono/16 kHz/16-bit, then atomically promotes it to
  `<stem>.16k-mono.wav` (default directory `output/`). It raises
  `NormalizationError` on failure and removes partial output. The source is
  never overwritten, deleted, or modified.

## Transcription (Slice 3a)

```python
from transcriptor.config import TranscriptionConfig
from transcriptor.transcriber import transcribe, TranscriptionError

result = transcribe("audio.m4a")
# result["language"], result["duration"], result["segments"], result["metrics"]
```

`transcribe(path, config=None)` validates, probes duration, and normalizes the
audio through the Slice 1+2 boundary first, then runs faster-whisper locally and
returns normalized segments and execution metrics. It never modifies the source.

- `TranscriptionConfig` defaults: `model="medium"`, `language="es"`,
  `device="cpu"`, `compute_type="int8"`, `vad_filter=True`, `beam_size=5`,
  `output_dir=Path("output")`, `download_root=None`, `local_files_only=False`.
- `download_root` selects the model cache directory; `local_files_only=True`
  prevents any download and uses only the cached model (offline).
- The module imports safely without faster-whisper installed; `transcribe()`
  raises `TranscriptionError` at invocation time when the runtime dependency or
  a cached model is missing.

### faster-whisper runtime and model cache

```bash
pip install -e ".[dev]"   # installs faster-whisper>=1.2.1 as a runtime dependency
```

The first online transcription downloads the configured model into the
HuggingFace cache (or `download_root`). For offline operation, pre-populate the
cache and set `local_files_only=True`.

### Real-model integration test (Slice 3b)

The suite adds one optional real `tiny` integration test that transcribes a
stdlib-generated 1-second WAV through the cached faster-whisper path with
`local_files_only=True`. Tests never download model weights.

- The test skips deterministically when faster-whisper is not installed or the
  `Systran/faster-whisper-tiny` snapshot is not already cached
  (`~/.cache/huggingface/hub`). Assertions are shape-only (segment types,
  timestamp bounds, finiteness, count relationship, source immutability) —
  never exact text.
- Pre-cache `tiny` once (~75 MB) to enable the offline test:

  ```bash
  huggingface-cli download Systran/faster-whisper-tiny
  ```

After pre-caching, run one real offline transcription directly (generates its
own isolated WAV; downloads nothing):

```bash
.venv/bin/python -c "
import wave
from pathlib import Path
f = Path('/tmp/tiny-tone.wav')
with wave.open(str(f), 'wb') as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
    w.writeframes(b'\x00\x00' * 16000)
from transcriptor.config import TranscriptionConfig
from transcriptor.transcriber import transcribe
r = transcribe(str(f), TranscriptionConfig(model='tiny', language='es', local_files_only=True, output_dir='/tmp'))
print('segments', len(r['segments']), 'language', r['language'], 'duration', round(r['duration'], 3), 'seconds', round(r['metrics']['processing_time_s'], 3))
"
```

## Slice Boundaries

**Slice 1**: bootstrap, pytest baseline, pure-stdlib audio input validation.

**Slice 2**: FFmpeg duration probing and 16 kHz mono normalization with
deterministic errors, source immutability, and staged cleanup.

**Slice 3a**: faster-whisper transcription core with config
defaults, normalized segments, metrics, and deterministic error mapping.

**Slice 3b**: optional cached real `tiny`-model integration test (offline,
shape-only) with pre-cache and direct-invocation docs.

**Not in this slice**: exporters, CLI, API, Django integration, and
`Yurbaco.m4a` processing.
