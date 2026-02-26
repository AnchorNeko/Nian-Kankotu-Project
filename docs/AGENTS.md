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
   - Prompt diagnostics outputs (effective keyframe/video prompts + injected character/background context + key generation parameters) in logs and CLI.
   - Style consistency requirements, reference-anchor strategy, and style diagnostics outputs.
4. Do not ship code changes that are not represented in architecture docs.
