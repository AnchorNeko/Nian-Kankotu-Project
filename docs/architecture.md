# Nian Kantoku FMVP Architecture

## Summary
This project turns a user-provided plot outline into a stitched anime-style video with document-first, layered architecture:
`interface -> application -> domain`, while `infrastructure` only implements application ports.

Pipeline phases:
1. Extract main characters from outline.
2. Generate character sheets (text + design images).
3. Generate storyboard (shots + background specs) with strict duration constraints.
4. Generate background sheets (text + design images) at location-level granularity.
5. Generate one keyframe image per shot with character/background design references.
6. Generate one video clip per shot with enriched prompts including shot + character + background context.
7. Merge clips into a final video when all shots succeed.
8. Emit detailed logs, events, and prompt diagnostics artifacts.

## Architecture Contract
```yaml
architecture_contract:
  version: "1.0.0"
  cli_command: "nian-kantoku run --outline-file <path> --output-dir <path> --config <path> [--reference-dir <path>] [--output-format <pretty|json>]"
  models:
    storyboard_text_model: "<config.models.storyboard_text_model>"
    image_model: "<config.models.image_model>"
    video_model: "<config.models.video_model>"
  default_output:
    resolution: "1280x720"
    fps: 24
  ports:
    - "StoryboardModelPort"
    - "ImageGeneratorPort"
    - "VideoGeneratorPort"
    - "AssetStorePort"
    - "ClipMergerPort"
    - "RuntimeDependencyPort"
  policy:
    max_storyboard_shot_duration_sec: 15
    overlong_storyboard_handling: "regenerate_offending_shots"
    max_regen_rounds_default: 3
    final_video_duration_hard_limit: false
    style_consistency_mode: "always_on"
    background_consistency_granularity: "location_level"
    design_asset_failure_handling: "fail_fast_before_shot_loop"
    style_anchor_strategy: "shot_related_character_background_designs_plus_user_refs_plus_previous_successful_keyframe"
    shot_failure_handling: "continue_and_mark_partial_failed"
    merge_condition: "merge_only_when_all_shots_succeed"
    partial_failure_exit_code: 2
    fail_fast_conditions:
      - "config_error"
      - "runtime_dependency_missing"
      - "character_extraction_failed"
      - "character_design_generation_failed"
      - "storyboard_generation_failed"
      - "background_design_generation_failed"
      - "regen_round_exhausted"
```

## Public Interfaces
- CLI entrypoint:
  - `nian-kantoku run --outline-file <path> --output-dir <path> --config <path> [--reference-dir <path>] [--output-format <pretty|json>]`
- Inputs:
  - Plot outline text (`.txt` or `.md`).
  - Optional reference image directory (`--reference-dir`) with naming convention:
    - `character_*`, `style_*`, `scene_*` (extensions: `.png`, `.jpg`, `.jpeg`, `.webp`).
- Outputs:
  - `character_sheet.json`
  - `background_sheet.json`
  - `storyboard.json`
  - `character_designs/*.png`
  - `background_designs/*.png`
  - `keyframes/shot_*.png`
  - `clips/shot_*.mp4`
  - `final.mp4`
  - `run_manifest.json`
  - `style_anchor_manifest.json`
  - `run.log`
  - `events.jsonl`
  - Terminal prompt diagnostics report (default `--output-format pretty`).

## Core Domain Types
- `CharacterSpec`
  - `character_id`, `display_name`, `identity_description`, `design_prompt`.
- `BackgroundSpec`
  - `background_id`, `display_name`, `location_description`, `visual_constraints`, `design_prompt`.
- `DesignAssetRecord`
  - `asset_id`, `asset_type`, `prompt`, `image_url`, `local_path`, `status`, `error_message`.
- `Shot`
  - `shot_id`, `duration_sec`, `story_beat`, `camera_instruction`, `image_prompt`, `video_prompt`,
    `character_ids`, `background_id`.
- `Storyboard`
  - `shots`, `backgrounds`, `style_guide`, `total_planned_duration`.
- `StoryboardValidationResult`
  - `valid_shots`, `offending_shots`, `regen_round`.
- `ShotExecutionRecord`
  - Existing render/prompt fields plus `character_ids`, `background_id`, `consistency_references_used`.
- `ShotDiagnosticsRecord`
  - One record per shot regardless of success/failure.
  - Includes storyboard/effective image prompt, storyboard/effective video prompt, key parameters,
    character/background linkage, consistency references, generated asset paths/URLs, and failure context.
- `ShotFailureRecord`
  - `shot_id`, `stage`, `error_message`.
- `RunManifest`
  - Existing run summary fields plus `character_designs`, `background_designs`,
    `records`, `shot_diagnostics`, `failed_records`, `merged_video_path`.

## Regeneration Workflow
1. Build storyboard prompt with explicit requirement: every shot duration must be `<= 15` seconds.
2. Force storyboard schema to include shot-level `character_ids` and `background_id`, plus top-level `backgrounds`.
3. Parse model JSON output.
4. Detect overlong shots (`duration_sec > 15`).
5. If any overlong shots exist:
   - Build a regeneration prompt listing offending shot ids and durations.
   - Ask model to regenerate only offending shots.
   - Merge regenerated shots back into existing storyboard.
6. Repeat until all shots satisfy duration rule, or `max_regen_rounds` is exceeded.
7. If exceeded, fail with detailed offending-shot context.

## Design Asset Policy
- Main characters are extracted before storyboard generation.
- Character design artifacts (text + image) are mandatory runtime inputs for shot generation.
- Background specs are generated in storyboard and then materialized to background design artifacts (text + image).
- If any required character/background design asset fails to generate and
  `consistency_assets.fail_on_missing_design_assets=true`, the run fails before shot loop.

## Video Duration Policy
- `shot.duration_sec` is a soft target for video generation.
- Generated clip durations are recorded in `run_manifest.json`.
- Clip duration mismatch does **not** fail the run.

## Shot Failure Policy
- Shot-level generation errors do not stop the entire run.
- The pipeline continues generating remaining shots and records failed shots in `run_manifest.json`.
- If any shot fails, clip merging is skipped and `final.mp4` is not produced.
- CLI exits with code `2` for partial failures after writing manifest and logs.

## Style and Scene Consistency Policy
- Keyframe style consistency is mandatory and always enabled.
- Keyframe prompt is built as:
  global style lock + character sheet context + background sheet context + shot prompt + continuity lock + anti-drift constraints.
- Video prompt is built as:
  shot video intent + character sheet context + background sheet context + render constraints.
- Per-shot reference images are selected with priority:
  1. shot-related character design images
  2. shot-related background design image
  3. user references (`character_*` -> `style_*` -> `scene_*`)
  4. previous successful keyframe image URLs (carry-over window from config)
- Image generation uses consistency controls from config:
  - `seed = base_seed + shot_index`
  - `guidance_scale`
  - `optimize_prompt` (default false)
- If image API rejects optional consistency parameters, adapter retries with progressive parameter downgrade and logs warnings.

## Observability
- Runtime emits human-readable logs to `run.log`.
- Runtime emits structured JSON Lines events to `events.jsonl`.
- Event payload includes at least:
  - `timestamp`, `level`, `event`, `stage`, `message`.
  - `shot_id`, `shot_index`.
  - `total_shots`, `completed_shots`, `failed_shots`.
  - `error` (if present).
  - `details` (structured diagnostics payload for prompts, references, and key parameters).
- Design-asset diagnostics must be logged:
  - Character extraction prompt/output summary.
  - Character/background design prompts, IDs, image URLs, local artifact paths, and failure context.
- Prompt diagnostics must be logged:
  - Effective keyframe prompt and effective storyboard-video prompt per shot.
  - Injected character/background sheet excerpts per shot.
  - Generated asset linkage (`keyframe_path`, `image_url`, `clip_path` when available).
- Terminal output defaults to a user-facing progress dashboard (not raw log lines).
  - `--output-format pretty`: live progress board during execution (Rich panel on TTY, compact progress lines on non-TTY), then concise summary + per-shot prompt/parameter details.
  - `--output-format json`: raw manifest JSON for machine-oriented workflows.

## Configuration & Security
- Sensitive config must come from environment variables only:
  - `ARK_API_KEY`
- Non-sensitive defaults in `config/settings.yaml`.
- Model selection must come from user-provided config files (`models.*`); code must not hardcode model IDs.
- Consistency controls must come from config (`style_consistency.*`, `consistency_assets.*`); no hidden hardcoded behavior switches.
- Required style consistency config keys:
  - `base_seed`, `guidance_scale`, `optimize_prompt`.
  - `max_reference_images_per_shot`, `carryover_prev_keyframes`.
  - `prompt_lock_preamble`, `retry_on_image_generation_error`.
- Required consistency asset config keys:
  - `max_main_characters`, `max_backgrounds`, `max_character_refs_per_shot`, `fail_on_missing_design_assets`.
- API keys must never be hardcoded or committed.

## Testing & Quality Gates
Every code change must pass:
1. `pytest -q`
2. `python scripts/verify_arch_sync.py`

Required test areas:
- Config loading and missing-secret behavior.
- Character/background design asset generation orchestration and fail-fast policy.
- Storyboard parsing and regeneration policy, including character/background linkage checks.
- Prompt template constraints.
- Ark adapter request shape and task polling behavior.
- End-to-end orchestration with fake adapters.
- Architecture document/code synchronization checks.

## Change Management Rules
1. Document-first: update architecture contract before code changes.
2. If code and docs drift, pause and ask the owner whether docs or code is source of truth.
3. After each change set, synchronize docs, code, and AGENTS rules.
4. Avoid coupling and hardcoded special-case branches. If special handling grows, extract strategy objects.
