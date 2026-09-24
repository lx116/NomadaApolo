"""Audio input validation and FFmpeg integration — pure stdlib."""

import math
import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path

SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".m4a", ".mp3", ".wav", ".mp4",".opus"})


class AudioProbeError(Exception):
    """Raised when ffprobe fails or returns invalid output."""


class NormalizationError(Exception):
    """Raised when ffmpeg normalization fails."""


def validate_audio_input(path: str | Path) -> Path:
    """Validate a local audio path and return it as a Path.

    Validation order:
    1. Construct Path.
    2. Existence check (FileNotFoundError).
    3. Regular-file check (ValueError).
    4. Suffix check, case-insensitive (ValueError).
    5. Binary-read open/close (propagates PermissionError / OSError).
    6. Return Path unchanged.
    """
    p = Path(path)

    if not p.exists():
        raise FileNotFoundError(f"Audio file not found: {p}")

    if not p.is_file():
        raise ValueError(f"Path is not a regular file: {p}")

    if p.suffix.lower() not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(
            f"Unsupported audio suffix '{p.suffix}'. Supported: {supported}"
        )

    with open(p, "rb") as f:
        pass  # ponytail: probe readability without decoding

    return p


def _resolve_executable(name: str) -> str:
    """Resolve a system executable via shutil.which; raise RuntimeError on miss."""
    exe = shutil.which(name)
    if not exe:
        raise RuntimeError(f"{name} not found")
    return exe


def probe_duration(path: str | Path) -> float:
    """Probe audio duration in seconds via system ffprobe.

    Raises RuntimeError if ffprobe is missing, AudioProbeError on failure.
    """
    p = validate_audio_input(path)
    ffprobe = _resolve_executable("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(p),
        ],
        shell=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        msg = f"ffprobe failed: {stderr}" if stderr else "ffprobe failed"
        raise AudioProbeError(msg)
    stdout = result.stdout.strip()
    if not stdout:
        raise AudioProbeError("ffprobe returned empty duration")
    try:
        duration = float(stdout)
    except (ValueError, TypeError):
        raise AudioProbeError(f"ffprobe returned non-numeric duration: {stdout!r}")
    if duration < 0 or not math.isfinite(duration):
        raise AudioProbeError(f"ffprobe returned invalid duration: {duration}")
    return duration


def _verify_wav(path: str) -> None:
    """Verify a WAV file is mono, 16 kHz, 16-bit PCM; raise NormalizationError."""
    try:
        with wave.open(path, "rb") as w:
            if w.getnchannels() != 1:
                raise NormalizationError(
                    f"WAV is not mono: channels={w.getnchannels()}"
                )
            if w.getframerate() != 16000:
                raise NormalizationError(
                    f"WAV is not 16kHz: rate={w.getframerate()}"
                )
            if w.getsampwidth() != 2:
                raise NormalizationError(
                    f"WAV is not 16-bit: sampwidth={w.getsampwidth()}"
                )
    except wave.Error as e:
        raise NormalizationError(f"Invalid WAV file: {e}") from e


def normalize_audio(
    path: str | Path, output_dir: str | Path | None = None
) -> Path:
    """Normalize audio to 16 kHz mono WAV without modifying the source.

    Returns the Path to the output file <stem>.16k-mono.wav.
    Raises NormalizationError on any failure; partial output is cleaned up.
    """
    p = validate_audio_input(path)
    try:
        ffmpeg = _resolve_executable("ffmpeg")
    except RuntimeError as e:
        raise NormalizationError(str(e)) from e

    out_dir = Path(output_dir) if output_dir else Path("output")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise NormalizationError(f"Cannot create output directory: {e}") from e

    final_path = out_dir / f"{p.stem}.16k-mono.wav"

    if final_path.resolve() == p.resolve():
        raise NormalizationError("Output path resolves to the source file")

    staged = None
    try:
        fd, staged = tempfile.mkstemp(suffix=".wav", dir=str(out_dir))
        os.close(fd)

        result = subprocess.run(
            [
                ffmpeg,
                "-nostdin", "-y",
                "-i", str(p),
                "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
                staged,
            ],
            shell=False,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            msg = f"ffmpeg failed: {stderr}" if stderr else "ffmpeg failed"
            raise NormalizationError(msg)

        if not os.path.exists(staged):
            raise NormalizationError("ffmpeg produced no output")

        _verify_wav(staged)

        os.replace(staged, str(final_path))
        staged = None  # ponytail: prevent cleanup after successful promote
        return final_path
    except NormalizationError:
        raise
    except Exception as e:
        raise NormalizationError(str(e)) from e
    finally:
        if staged and os.path.exists(staged):
            os.unlink(staged)
