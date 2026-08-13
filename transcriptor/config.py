"""Transcription configuration defaults and overrides."""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptionConfig:
    """faster-whisper execution options with stable, documented defaults."""

    model: str = "medium"
    language: str = "es"
    device: str = "cpu"
    compute_type: str = "int8"
    vad_filter: bool = True
    beam_size: int = 5
    output_dir: Path = Path("output")
    download_root: Path | None = None
    local_files_only: bool = False
