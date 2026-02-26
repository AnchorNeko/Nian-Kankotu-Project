# AGENTS.md (src/nian_kantoku)

## Architecture Rules
1. Application layer can depend only on domain and ports.
2. Infrastructure layer can depend on SDK/system tools but must implement application ports.
3. Interface layer (CLI) must not call SDK directly; call application use cases only.

## Policy Rules
1. For storyboard output with shots over 15 seconds, run regeneration of offending shots; do not fail immediately.
2. Enforce max regeneration rounds from config; fail only after rounds are exhausted.
3. Do not enforce hard duration limits on generated video clips.
4. Character extraction and character design generation must run before storyboard shot loop.
5. Background design generation must run from storyboard location-level backgrounds before shot loop.
6. When fail-fast consistency policy is enabled, missing required design assets must fail the run before shot loop.
7. Shot-level generation failures must be recorded and reported; continue remaining shots and mark run as partial failed.
8. If any shot fails, skip final merge while still writing manifest and logs for diagnostics.
9. Keyframe generation must enforce cross-shot style consistency using global style lock + shot-related character/background anchors.
10. Reference anchor priority is fixed: shot-related character/background design assets, then user references, then previous successful keyframes.
11. Replace repeated special-case branching with policy/strategy abstractions.
12. Persist per-shot prompt diagnostics (image/video prompts plus injected consistency context and key parameters) into run artifacts and expose them in CLI user output.
13. CLI must present runtime progress via dashboard-oriented rendering, while raw logs stay in artifacts.
