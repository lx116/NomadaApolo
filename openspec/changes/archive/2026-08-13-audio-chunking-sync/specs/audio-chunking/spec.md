# Audio Chunking Specification

## Purpose

Define deterministic, isolated synchronous chunking while preserving the source (AC-001..AC-005).

## Requirements

### Requirement: Immutable source and isolated workspace

The system MUST read the source without modifying, moving, renaming, or deleting it. It MUST create a restricted, unique `<tmp_root>/<job_id>/` workspace outside repository paths and MUST emit its manifest before transcription.

#### Scenario: Long source is chunked

- GIVEN a readable source of at least 300 seconds and a unique job ID
- WHEN chunking runs
- THEN the workspace, ordered manifest, and source hash are created without changing source bytes

#### Scenario: Workspace collision

- GIVEN the requested job workspace already exists
- WHEN chunking starts
- THEN the operation fails without mixing artifacts or overwriting the existing workspace

### Requirement: Deterministic bounded chunks

The system MUST bypass physical chunking for sources shorter than 300 seconds. Otherwise it MUST create ordered chunks of at most 300 seconds with configurable 1–2 second overlap, deterministic six-digit names, and source/content offsets. The final shorter chunk MUST be retained when readable (AC-002..AC-004).

#### Scenario: Boundary durations

- GIVEN sources of 299.9 and 300.0 seconds
- WHEN chunking runs
- THEN the first produces one logical original unit and the second produces bounded physical chunks with the configured overlap

#### Scenario: Interrupted write

- GIVEN chunk extraction is interrupted
- WHEN the write fails
- THEN no partial chunk is accepted as valid and the source remains unchanged (AC-005)
