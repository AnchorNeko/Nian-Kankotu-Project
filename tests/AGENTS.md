# AGENTS.md (tests)

## Test Rules
1. Every behavior change requires tests or explicit test-impact rationale.
2. Cover happy path and failure path for orchestration.
3. Include tests for storyboard overlong-shot regeneration behavior.
4. Include tests for character/background design generation and fail-fast policy.
5. Include architecture synchronization checks in test flow.
6. Verify prompt diagnostics coverage in both run artifacts (`run_manifest.json`, `events.jsonl`) and CLI user-facing output.
7. Verify CLI user-facing output avoids raw log-line streaming.
