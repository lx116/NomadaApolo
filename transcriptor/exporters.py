"""Atomic staged publication of JSON + TXT from one ordered segment list (AC-009..AC-011)."""

import json
import os
import tempfile
from pathlib import Path

EXPORT_MARKER = "export.complete"


def format_timestamp(seconds):
    """Absolute seconds -> ``HH:MM:SS``."""
    total = max(0, int(round(float(seconds))))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def render_txt(segments):
    """One ``[HH:MM:SS - HH:MM:SS]`` header line per segment plus its text."""
    lines = []
    for seg in segments:
        lines.append(f"[{format_timestamp(seg['start'])} - {format_timestamp(seg['end'])}]")
        lines.append(seg["text"])
    return "\n".join(lines) + "\n"


def _write_json_atomic(path, obj):
    fd, staged = tempfile.mkstemp(dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=True)
    os.replace(staged, str(path))


def _write_text_atomic(path, text):
    fd, staged = tempfile.mkstemp(dir=str(path.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(staged, str(path))


def export_aggregate(aggregate, output_dir, *, json_name="transcription.json",
                     txt_name="transcription.txt", marker_name=EXPORT_MARKER):
    """Publish JSON + TXT together; announce (return paths) only after both promote.

    On TXT promotion failure the already-promoted JSON sibling is removed so no
    half-pair survives. Both files derive from the same ``aggregate["segments"]``.
    """
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path, txt_path, marker = out / json_name, out / txt_name, out / marker_name

    _write_json_atomic(json_path, aggregate)
    try:
        _write_text_atomic(txt_path, render_txt(aggregate["segments"]))
    except Exception:
        if json_path.exists():
            json_path.unlink()
        raise
    _write_text_atomic(marker, "complete\n")
    return json_path, txt_path
