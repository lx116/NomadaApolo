"""Standalone runner for the synchronous chunking pipeline.

Run this cell in a Jupyter notebook or execute as a script. It expects
`Yurbaco.m4a` at the repository root and writes the final outputs to
`output/transcription/`.
"""

import shutil
import json
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from transcriptor.pipeline import run

REPO_ROOT = Path(__file__).resolve().parent
SOURCE = REPO_ROOT / "Yurbaco.m4a"
TMP_ROOT = Path("/tmp/nomada-jobs")  # must be outside the git repo
OUTPUT_DIR = REPO_ROOT / "output"
JOB_ID = "yurbaco"

if not SOURCE.exists():
    raise FileNotFoundError(f"Audio not found: {SOURCE}")

# The chunker refuses to reuse an existing workspace, so clean it first.
job_workspace = TMP_ROOT / JOB_ID
if job_workspace.exists():
    shutil.rmtree(job_workspace)

print(f"Processing: {SOURCE}", flush=True)
print(f"Temporary workspace: {TMP_ROOT}", flush=True)
print(f"Final output directory: {OUTPUT_DIR / 'transcription'}", flush=True)


def transcribe():
    return run(
        str(SOURCE),
        str(TMP_ROOT),
        JOB_ID,
        output_dir=str(OUTPUT_DIR),
        model="medium",
        language="es",
        device="cpu",
        compute_type="int8",
        chunk_seconds=300.0,
        overlap=1.0,
        on_chunk_completed=print_chunk,
    )


def print_chunk(result, duration_s):
    texts = " ".join(segment["text"] for segment in result["segments"])
    print(f"\n--- Chunk {result['chunk_index'] + 1} completed in {duration_s:.2f}s ---", flush=True)
    print(texts or "[No text detected]", flush=True)


def show_progress(future):
    reported_chunks = set()
    started = time.monotonic()
    while not future.done():
        checkpoint = job_workspace / "checkpoint.json"
        manifest = job_workspace / "manifest.json"
        if checkpoint.exists() and manifest.exists():
            state = json.loads(checkpoint.read_text(encoding="utf-8"))
            total = len(json.loads(manifest.read_text(encoding="utf-8"))["chunks"])
            completed = sum(c["state"] == "completed" for c in state["chunks"])
            active = state.get("active_chunk")
            active_elapsed = 0.0
            active_label = "none"
            if active:
                started_at = datetime.fromisoformat(active["started_at"].replace("Z", "+00:00"))
                active_elapsed = (datetime.now(timezone.utc) - started_at).total_seconds()
                active_label = f"{active['index'] + 1}/{total}"
            print(
                f"\rElapsed {time.monotonic() - started:7.1f}s | {state['state']} | "
                f"chunk {active_label} | chunk elapsed {active_elapsed:7.1f}s | "
                f"completed {completed}/{total}", end="", flush=True,
            )
            for chunk in state["chunks"]:
                index = chunk["index"]
                if index not in reported_chunks and chunk["state"] == "completed":
                    duration = chunk.get("duration_s")
                    if duration is not None:
                        print(f"\n  Chunk {index + 1}/{total} completed in {duration:.2f}s", flush=True)
                    reported_chunks.add(index)
        else:
            print("\rElapsed preparing chunks...", end="", flush=True)
        time.sleep(1)


with ThreadPoolExecutor(max_workers=1) as executor:
    future = executor.submit(transcribe)
    show_progress(future)
    result = future.result()

print("\r" + " " * 100 + "\r", end="")
print("Done.")
print(f"  JSON: {result['json']}")
print(f"  TXT:  {result['txt']}")
print(f"  Segments: {len(result['aggregate']['segments'])}")
print(f"  Duration: {result['aggregate']['duration']:.2f} s")
