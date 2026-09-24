---
name: codex-code-changes
description: Trigger: any request that creates, edits, deletes, or renames source code in NomadaApolo, including SDD sdd-apply and remediation work. Route every code alteration through the Codex plugin; the orchestrator plans, delegates, and verifies but never edits code itself.
---

# Codex-Only Code Changes

Codex holds the highest-tier plan for this project, so it is the only actor that alters code.

## What counts as code

Python, Django templates, HTML/CSS/JS, Tailwind config, migrations, tests, fixtures, and dependency or build files (`pyproject.toml`).

Not code (any agent may edit): SDD artifacts in Engram, `AGENTS.md`, skill files, docs, and memory.

## Rules

1. The orchestrator and every non-Codex sub-agent (including `sdd-apply`) MUST NOT use Edit, Write, NotebookEdit, or shell redirection to change code.
2. Code changes are delegated to Codex through the `codex:codex-rescue` agent (or the `/codex:rescue` skill), one SDD task slice per run. If the agent fails with `failed to initialize in-process app-server client: Operation not permitted`, run the same prompt from the main shell: `node ~/.claude/plugins/cache/openai-codex/codex/1.0.6/scripts/codex-companion.mjs task --write --fresh "$(bat -p <prompt-file>)"`, redirecting stdout to a scratchpad file (never `tail` it: the RED evidence gets cut). Keep the prompt file in the scratchpad, not in the repo.
3. Before the first delegation in a session, confirm Codex is ready (`codex:setup`). If it is unavailable, STOP and report. Never fall back to editing code directly.
4. Each Codex prompt must carry: the change name, the exact slice from `sdd/{change}/tasks`, references to the `spec` and `design` topic keys, Strict TDD mode (`.venv/bin/python -m pytest -q`, test first), Ponytail minimal-solution rules, the 400 changed-line budget, and the English-only rule for code and comments.
5. Codex must not commit, push, or touch files outside the slice. Commits use conventional commits without AI attribution.
6. Codex must not write or update Engram SDD artifacts. It can, and it has: it overwrote `apply-progress` once and later rewrote a whole change's proposal/spec/design/tasks and created fake `verify-report`/`archive-report` entries. Every prompt MUST open with: "This is NOT an SDD run. Do not use any sdd-* skill. Do not call ANY mem_* tool (no save, update, search, summary)." After every Codex run, compare the change's Engram artifacts against a pre-run `engram export` snapshot and restore any that changed (originals live in the subagent transcripts, or in the scratchpad copies), then soft-delete fake reports with `engram delete <id>`.
7. Codex's sandbox has no network: dependency installs (`pip`, `uv`) are done by the orchestrator in the shell, not by Codex.

## After every Codex run

1. Read Codex's report and run `git diff --stat` to confirm only slice files changed and the diff stays within 400 lines.
2. Run `.venv/bin/python -m pytest -q` and report the real output.
3. Persist progress to `sdd/{change}/apply-progress`: the orchestrator records it, merging with prior progress, and re-reads the topic first in case Codex modified it.
4. If verification fails, send one scoped correction back to Codex. Do not patch the code inline.

## SDD mapping

- Planning phases (explore, propose, spec, design, tasks) stay with the normal SDD agents.
- `sdd-apply` work is executed by Codex; the orchestrator supplies the apply contract and records apply-progress.
- `sdd-verify` may run tests and read code but must not modify it; fixes go back through Codex.
