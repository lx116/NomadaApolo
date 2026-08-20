# Audio Preprocessing Specification

## Purpose

Normalize each chunk for transcription without silently changing meaning (AC-005..AC-007).

## Requirements

### Requirement: Whisper-compatible chunk output

The system MUST produce each successful chunk as PCM mono, 16 kHz, 16-bit audio in the job workspace. It MUST record input/output paths, durations, FFmpeg version, command parameters, and source offsets. Failures MUST identify the chunk and MUST remove partial output.

#### Scenario: Valid normalization

- GIVEN a valid manifest chunk and available FFmpeg
- WHEN preprocessing completes
- THEN the output passes mono/16 kHz/16-bit validation and its metadata preserves the source interval

#### Scenario: FFmpeg failure

- GIVEN FFmpeg is unavailable or fails during output
- WHEN preprocessing runs
- THEN it returns an actionable error with stage, chunk, command, and stderr summary and leaves no valid partial output (AC-005)

### Requirement: Separate conservative filters

VAD/silence trimming and denoising MUST be independently configurable and recorded. Denoising MUST be disabled by default; neither option MAY silently delete or rewrite literal transcription text (AC-006..AC-007).

#### Scenario: Filter metadata

- GIVEN VAD is enabled and denoising is disabled
- WHEN a chunk is processed
- THEN metadata records those states distinctly, including the selected mode and filter

#### Scenario: Ambiguous acoustic content

- GIVEN a filter cannot confidently classify speech or noise
- WHEN preprocessing runs
- THEN the chunk remains available for transcription and no text is discarded by heuristic inference
