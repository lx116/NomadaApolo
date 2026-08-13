# NomadaApolo Project Instructions

## Mandatory Coding Workflow

- Ponytail is always active for coding work at the default `full` level. Apply its minimal-solution ladder, avoid speculative abstractions, and do not add dependencies or scaffolding without a concrete requirement.
- Every non-trivial product or code change must begin with an SDD preflight. Confirm the project context, existing artifacts, affected scope, testing capability, and delivery boundary before editing.
- Follow this SDD lifecycle in order: proposal, spec, design, tasks, apply, verify, archive.
- Use Engram as the artifact store for SDD artifacts and progress. Do not create `openspec/` artifacts unless explicitly requested.
- Execution mode is `auto`.
- Delivery strategy is `force-chained`. Keep implementation and review slices within a 400 changed-line review budget.
- Technical artifacts, configuration, comments, and code must be written in English.

## Skill Resolution

- Read the current project registry at `.atl/skill-registry.md` when resolving applicable skills. It is an index only; read the exact source `SKILL.md` for each selected skill.
- The registry is current. Do not regenerate it unless skills are installed, removed, created, moved, or renamed.
- Ponytail source: `/Users/luisvelez/.cache/opencode/packages/@dietrichgebert/ponytail@latest/node_modules/@dietrichgebert/ponytail/skills/ponytail/SKILL.md`.
- SDD phase skills: `/Users/luisvelez/.config/opencode/skills/sdd-{propose,spec,design,tasks,apply,verify,archive}/SKILL.md`.
- Shared SDD references: `/Users/luisvelez/.config/opencode/skills/_shared/SKILL.md`.

## Project Constraints

- This is a fresh Django scaffold without a Git repository. Do not assume Git branches, commits, or pull requests exist; preserve the configured chained delivery policy for future repository work.
- Do not create speculative commands, plugins, dependencies, tests, or product code.
