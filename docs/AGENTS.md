# AGENTS.md (docs)

## Documentation-First Rules
1. `docs/architecture.md` must be updated before implementation when behavior/interfaces change.
2. Keep the `architecture_contract` YAML block accurate and current.
3. Keep policy statements explicit for:
   - Overlong storyboard shot regeneration.
   - No hard duration limit on generated video clips.
   - Character/background design-asset generation order and fail-fast boundary.
   - Shot-failure continuation and partial-failure boundaries.
   - Runtime observability outputs (`run.log`, `events.jsonl`) and CLI exit semantics.
   - User-facing CLI progress dashboard behavior (no raw log-line streaming to users).
   - Prompt diagnostics outputs in `shot_diagnostics.jsonl` and CLI.
   - Style consistency requirements, reference-anchor strategy, and strict adapter fallback policy.
4. Do not ship code changes that are not represented in architecture docs.
