"""Per-chunk FFmpeg preprocessing: mono/16 kHz/16-bit, conservative filters (AC-005..AC-007)."""

import os
import subprocess
import tempfile
from pathlib import Path

from transcriptor.audio import _resolve_executable, _verify_wav

class PreprocessError(Exception):
    """Raised when preprocessing a chunk fails."""

def ffmpeg_version(ffmpeg):
    try:
        result = subprocess.run([ffmpeg, "-version"], shell=False, capture_output=True, text=True)
        lines = result.stdout.strip().splitlines()
        return lines[0] if lines else "unknown"
    except Exception:
        return "unknown"

def preprocess_chunk(input_path, output_dir, chunk_index, *, source_start, source_end,
                     vad_enabled=False, vad_mode="silence-context-only",
                     denoise_enabled=False, denoise_filter=None):
    """Convert one chunk to PCM mono 16 kHz 16-bit WAV and return its metadata."""
    out_dir = Path(output_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise PreprocessError(f"chunk {chunk_index}: cannot create output directory: {e}") from e
    final_path = out_dir / f"{chunk_index:06d}.wav"
    try:
        ffmpeg = _resolve_executable("ffmpeg")
    except RuntimeError as e:
        raise PreprocessError(f"chunk {chunk_index}: {e}") from e
    # ponytail: conservative filters only; VAD trims silence, denoise uses afftdn.
    denoise_used = denoise_filter or ("afftdn" if denoise_enabled else None)
    filters = []
    if vad_enabled:
        filters.append("silenceremove=start_periods=1:start_silence=0.2:start_threshold=-50dB")
    if denoise_used:
        filters.append(denoise_used)
    staged = None
    try:
        fd, staged = tempfile.mkstemp(prefix=".p.", suffix=".wav", dir=str(out_dir))
        os.close(fd)
        argv = [ffmpeg, "-nostdin", "-y", "-i", str(input_path), "-vn",
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le"]
        if filters:
            argv += ["-af", ",".join(filters)]
        argv.append(staged)
        result = subprocess.run(argv, shell=False, capture_output=True, text=True)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise PreprocessError(f"chunk {chunk_index}: ffmpeg failed: {stderr or 'ffmpeg failed'}")
        if not os.path.exists(staged):
            raise PreprocessError(f"chunk {chunk_index}: ffmpeg produced no output")
        _verify_wav(staged)
        os.replace(staged, str(final_path))
        staged = None
        return {
            "chunk_index": chunk_index, "input_chunk": str(input_path),
            "output_audio": str(final_path), "sample_rate": 16000, "channels": 1,
            "sample_format": "s16",
            "vad": {"enabled": vad_enabled, "mode": vad_mode if vad_enabled else None},
            "denoising": {"enabled": denoise_enabled, "filter": denoise_used},
            "source_start": float(source_start), "source_end": float(source_end),
            "ffmpeg_version": ffmpeg_version(ffmpeg),
        }
    except PreprocessError:
        raise
    except Exception as e:
        raise PreprocessError(f"chunk {chunk_index}: {e}") from e
    finally:
        if staged and os.path.exists(staged):
            os.unlink(staged)
