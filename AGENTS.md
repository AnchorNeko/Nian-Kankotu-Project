# AGENTS.md (Repository Root)

## Mission
Implement and evolve Nian Kantoku using document-first, layered architecture, and strict quality gates.

## Hard Rules
1. Follow `docs/architecture.md` as the current contract before coding.
2. Keep dependency direction strict: `interface -> application -> domain`; infrastructure only implements ports.
3. Never hardcode secrets in code, configs, tests, or docs.
4. Every behavioral or interface change must update architecture docs and AGENTS rules in the same change set.
5. If docs and code disagree, stop and ask the owner which state to follow.
6. If logic accumulates many special cases, refactor into strategy/policy abstractions.
7. Runtime observability is mandatory: each run must emit detailed logs and structured progress events under the run output directory.
8. Shot-level failures must be captured and reported; partial failures must still produce diagnostics artifacts.
9. Keyframe style consistency is mandatory and always-on: preserve character identity, outfit continuity, and visual style across shots with reference anchors.
10. Prompt observability is mandatory: keyframe/video prompts and key generation parameters must be present in run logs, structured events, and `shot_diagnostics.jsonl`.
11. CLI runtime UX must use a progress dashboard; do not expose raw structured log lines directly to end users.
12. Character/background consistency assets are mandatory runtime artifacts: generate character sheets first, then background sheets before shot loop.
13. If required character/background design assets are missing under fail-fast policy, stop before shot generation.
14. Shot generation must inject only shot-related character/background consistency assets plus configured carry-over references.
15. Adapter compatibility fallbacks must be explicit: do not use exception-text heuristics or recursive deep-search extraction.

## Required Validation
Run both commands before finalizing any change:
- `pytest -q`
- `python scripts/verify_arch_sync.py`
