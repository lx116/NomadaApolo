# Chunk Transcription Specification

## Purpose

Transcribe normalized chunks with one synchronous model lifecycle and traceable absolute timing (AC-007, AC-008, AC-011, AC-012).

## Requirements

### Requirement: Literal, offset-correct transcription

The system MUST load one model instance per synchronous job and reuse it for compatible chunks. Every segment MUST preserve literal `text`, local timing, absolute `start`/`end`, `source_start`/`source_end`, chunk index, and stable ID. It MUST record model, device, configuration, durations, counts, and errors.

#### Scenario: Multiple chunks

- GIVEN two normalized chunks with local segments
- WHEN the job transcribes them
- THEN the model is created once and each segment receives absolute offsets equal to chunk start plus local offset

#### Scenario: Ambiguous model text

- GIVEN the model returns spaces, repetitions, capitalization, or doubtful text
- WHEN the segment is stored
- THEN the text is preserved literally and remains visible and traceable

### Requirement: Bounded retry and reuse

The system MUST retry only the failing chunk under an explicit bounded policy. A validated chunk MUST be reused only when `source_id` and configuration fingerprint match; definitive input/model errors MUST fail diagnostically (AC-011..AC-012).

#### Scenario: Compatible resume

- GIVEN one validated chunk and an unchanged source/configuration
- WHEN transcription resumes
- THEN that chunk is not reprocessed and no duplicate segment ID is produced

#### Scenario: Chunk failure

- GIVEN a transient failure for one chunk
- WHEN retry is allowed
- THEN only that chunk is retried, while confirmed chunks remain untouched
