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

## Slice Boundaries

**Slice 1**: bootstrap, pytest baseline, pure-stdlib audio input validation.

**Slice 2 (this change)**: FFmpeg duration probing and 16 kHz mono
normalization with deterministic errors, source immutability, and staged
cleanup.

**Not in this slice**: faster-whisper transcription, model downloads, VAD,
exporters, CLI, API, Django integration, `Yurbaco.m4a` processing.
