from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

from nian_kantoku.application.config import AppConfig
from nian_kantoku.application.exceptions import PipelineExecutionError, StoryboardRegenerationError
from nian_kantoku.application.ports import (
    AssetStorePort,
    ClipMergerPort,
    ImageGeneratorPort,
    RuntimeDependencyPort,
    StoryboardModelPort,
    VideoGeneratorPort,
)
from nian_kantoku.application.prompt_templates import (
    build_anti_drift_constraints,
    build_background_design_prompt,
    build_character_design_prompt,
    build_character_extraction_prompt,
    build_effective_image_prompt,
    build_effective_video_prompt,
    build_global_style_lock_text,
    build_shot_continuity_lock_text,
    build_storyboard_prompt,
    build_storyboard_regeneration_prompt,
)
from nian_kantoku.application.storyboard_parser import (
    merge_storyboard_with_regenerated_shots,
    parse_storyboard,
    validate_storyboard,
    validate_storyboard_references,
)
from nian_kantoku.domain.models import (
    AssetLayout,
    BackgroundSpec,
    CharacterSpec,
    DesignAssetRecord,
    RunManifest,
    Shot,
    ShotDiagnosticsRecord,
    ShotExecutionRecord,
    ShotFailureRecord,
    Storyboard,
    VideoTaskStatus,
)


_SUCCEEDED_STATUSES = {"succeeded", "success", "completed", "done"}
_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "rejected", "timeout"}
_STYLE_ANCHOR_MANIFEST_FILE = "style_anchor_manifest.json"


@dataclass(frozen=True)
class GenerateAnimeVideoRequest:
    outline_file: Path
    output_dir: Path
    reference_images: Sequence[str] = field(default_factory=tuple)
    reference_image_labels: Sequence[str] = field(default_factory=tuple)


class GenerateAnimeVideoUseCase:
    def __init__(
        self,
        *,
        config: AppConfig,
        storyboard_model: StoryboardModelPort,
        image_generator: ImageGeneratorPort,
        video_generator: VideoGeneratorPort,
        asset_store: AssetStorePort,
        clip_merger: ClipMergerPort,
        runtime_dependency: RuntimeDependencyPort,
    ) -> None:
        self._config = config
        self._storyboard_model = storyboard_model
        self._image_generator = image_generator
        self._video_generator = video_generator
        self._asset_store = asset_store
        self._clip_merger = clip_merger
        self._runtime_dependency = runtime_dependency
        self._logger = logging.getLogger("nian_kantoku.run")

    def execute(self, request: GenerateAnimeVideoRequest) -> RunManifest:
        self._log_event(
            event="run_started",
            stage="run",
            message="Video generation run started",
        )
        self._runtime_dependency.ensure_ffmpeg()
        self._log_event(
            event="runtime_dependency_checked",
            stage="runtime_check",
            message="ffmpeg runtime dependency check passed",
        )

        layout = self._asset_store.prepare_layout(
            output_dir=request.output_dir,
            character_sheet_file_name=self._config.paths.character_sheet_file,
            background_sheet_file_name=self._config.paths.background_sheet_file,
            character_designs_dir_name=self._config.paths.character_designs_dir,
            background_designs_dir_name=self._config.paths.background_designs_dir,
            storyboard_file_name=self._config.paths.storyboard_file,
            keyframes_dir_name=self._config.paths.keyframes_dir,
            clips_dir_name=self._config.paths.clips_dir,
            final_video_file_name=self._config.paths.final_video_file,
            run_manifest_file_name=self._config.paths.run_manifest_file,
        )
        self._log_event(
            event="layout_prepared",
            stage="layout",
            message=f"Output layout prepared at {layout.output_dir}",
        )

        outline = self._asset_store.read_text(file_path=request.outline_file)
        self._log_event(
            event="outline_loaded",
            stage="storyboard",
            message=f"Loaded outline from {request.outline_file}",
        )

        character_specs = self._extract_main_characters(outline=outline)
        self._asset_store.write_json(
            file_path=layout.character_sheet_file,
            payload={"characters": [item.to_dict() for item in character_specs]},
        )
        self._log_event(
            event="character_sheet_written",
            stage="character_extraction",
            message=f"Character sheet written to {layout.character_sheet_file}",
            details={"character_count": len(character_specs)},
        )

        character_design_records = self._generate_character_design_assets(
            layout=layout,
            character_specs=character_specs,
        )
        self._enforce_required_design_assets(
            records=character_design_records,
            stage="character_design",
            asset_type="character",
        )

        storyboard, regen_rounds, offending_history = self._generate_storyboard_with_regeneration(
            outline=outline,
            character_specs=character_specs,
        )
        total_shots = len(storyboard.shots)
        self._asset_store.write_json(
            file_path=layout.storyboard_file,
            payload=storyboard.to_dict(),
        )
        self._log_event(
            event="storyboard_saved",
            stage="storyboard",
            message=f"Storyboard written to {layout.storyboard_file}",
            total_shots=total_shots,
        )

        self._asset_store.write_json(
            file_path=layout.background_sheet_file,
            payload={"backgrounds": [item.to_dict() for item in storyboard.backgrounds]},
        )
        self._log_event(
            event="background_sheet_written",
            stage="background_design",
            message=f"Background sheet written to {layout.background_sheet_file}",
            details={"background_count": len(storyboard.backgrounds)},
        )

        background_design_records = self._generate_background_design_assets(
            layout=layout,
            storyboard=storyboard,
            character_specs=character_specs,
        )
        self._enforce_required_design_assets(
            records=background_design_records,
            stage="background_design",
            asset_type="background",
        )

        character_specs_by_id = {item.character_id: item for item in character_specs}
        background_specs_by_id = {item.background_id: item for item in storyboard.backgrounds}
        character_design_refs = {
            item.asset_id: (item.image_url, f"character_design:{item.asset_id}")
            for item in character_design_records
            if item.status == "succeeded" and item.image_url
        }
        background_design_refs = {
            item.asset_id: (item.image_url, f"background_design:{item.asset_id}")
            for item in background_design_records
            if item.status == "succeeded" and item.image_url
        }

        global_style_lock_text = build_global_style_lock_text(
            style_guide=storyboard.style_guide,
            lock_preamble=self._config.style_consistency.prompt_lock_preamble,
        )
        anti_drift_constraints = build_anti_drift_constraints()

        records: List[ShotExecutionRecord] = []
        shot_diagnostics: List[ShotDiagnosticsRecord] = []
        failed_records: List[ShotFailureRecord] = []
        clip_paths: List[Path] = []
        style_anchor_records: List[Dict[str, object]] = []
        completed_shots = 0
        failed_shots = 0
        previous_successful_references: List[Tuple[str, str]] = []
        previous_successful_shot_id: str | None = None
        previous_successful_story_beat: str | None = None

        for shot_index, shot in enumerate(storyboard.shots, start=1):
            current_stage = "shot_start"
            shot_seed = self._config.style_consistency.base_seed + shot_index

            shot_character_specs = [
                character_specs_by_id[char_id]
                for char_id in shot.character_ids
                if char_id in character_specs_by_id
            ]
            shot_background_spec = background_specs_by_id.get(shot.background_id)
            character_context = self._build_character_context(shot_character_specs)
            background_context = self._build_background_context(shot_background_spec)

            reference_images, reference_labels = self._select_reference_images(
                shot=shot,
                character_design_refs=character_design_refs,
                background_design_refs=background_design_refs,
                user_reference_images=request.reference_images,
                user_reference_labels=request.reference_image_labels,
                previous_successful_references=previous_successful_references,
            )

            continuity_lock_text = build_shot_continuity_lock_text(
                previous_shot_id=previous_successful_shot_id,
                previous_story_beat=previous_successful_story_beat,
            )
            effective_image_prompt = build_effective_image_prompt(
                global_style_lock_text=global_style_lock_text,
                character_context=character_context,
                background_context=background_context,
                shot_image_prompt=shot.image_prompt,
                continuity_lock_text=continuity_lock_text,
                anti_drift_constraints=anti_drift_constraints,
            )
            effective_video_prompt = build_effective_video_prompt(
                shot_video_prompt=shot.video_prompt,
                character_context=character_context,
                background_context=background_context,
                shot_duration_sec=shot.duration_sec,
                render_width=self._config.render.width,
                render_height=self._config.render.height,
                render_fps=self._config.render.fps,
            )

            shot_diagnostic = ShotDiagnosticsRecord(
                shot_id=shot.shot_id,
                shot_index=shot_index,
                status="in_progress",
                planned_duration_sec=shot.duration_sec,
                storyboard_image_prompt=shot.image_prompt,
                storyboard_video_prompt=shot.video_prompt,
                effective_image_prompt=effective_image_prompt,
                effective_video_prompt=effective_video_prompt,
                image_model=self._config.models.image_model,
                video_model=self._config.models.video_model,
                image_seed=shot_seed,
                image_guidance_scale=self._config.style_consistency.guidance_scale,
                image_optimize_prompt=self._config.style_consistency.optimize_prompt,
                render_width=self._config.render.width,
                render_height=self._config.render.height,
                render_fps=self._config.render.fps,
                reference_images_used=list(reference_labels),
                character_ids=list(shot.character_ids),
                background_id=shot.background_id,
                consistency_references_used=list(reference_labels),
            )
            shot_diagnostics.append(shot_diagnostic)

            style_anchor_record: Dict[str, object] = {
                "shot_id": shot.shot_id,
                "shot_index": shot_index,
                "seed": shot_seed,
                "guidance_scale": self._config.style_consistency.guidance_scale,
                "optimize_prompt": self._config.style_consistency.optimize_prompt,
                "reference_images_used": reference_labels,
                "reference_count": len(reference_images),
                "continuity_from_shot_id": previous_successful_shot_id,
                "character_ids": shot.character_ids,
                "background_id": shot.background_id,
                "storyboard_image_prompt": shot.image_prompt,
                "effective_image_prompt": effective_image_prompt,
                "storyboard_video_prompt": shot.video_prompt,
                "effective_video_prompt": effective_video_prompt,
                "image_model": self._config.models.image_model,
                "video_model": self._config.models.video_model,
                "render_width": self._config.render.width,
                "render_height": self._config.render.height,
                "render_fps": self._config.render.fps,
                "status": "pending",
            }
            style_anchor_records.append(style_anchor_record)

            self._log_event(
                event="style_anchor_selected",
                stage="style_consistency",
                message=(
                    f"Selected {len(reference_images)} reference anchors for {shot.shot_id}: "
                    f"{reference_labels}"
                ),
                shot_id=shot.shot_id,
                shot_index=shot_index,
                total_shots=total_shots,
                completed_shots=completed_shots,
                failed_shots=failed_shots,
                details={
                    "character_ids": shot.character_ids,
                    "background_id": shot.background_id,
                    "consistency_references_used": reference_labels,
                },
            )
            self._log_event(
                event="image_params_applied",
                stage="style_consistency",
                message=(
                    f"Applied image controls for {shot.shot_id}: seed={shot_seed}, "
                    f"guidance_scale={self._config.style_consistency.guidance_scale}, "
                    f"optimize_prompt={self._config.style_consistency.optimize_prompt}"
                ),
                shot_id=shot.shot_id,
                shot_index=shot_index,
                total_shots=total_shots,
                completed_shots=completed_shots,
                failed_shots=failed_shots,
            )
            self._log_event(
                event="shot_started",
                stage="shot",
                message=f"Start generating shot {shot.shot_id} ({shot_index}/{total_shots})",
                shot_id=shot.shot_id,
                shot_index=shot_index,
                total_shots=total_shots,
                completed_shots=completed_shots,
                failed_shots=failed_shots,
                details={
                    "storyboard_image_prompt": shot.image_prompt,
                    "effective_image_prompt": effective_image_prompt,
                    "storyboard_video_prompt": shot.video_prompt,
                    "effective_video_prompt": effective_video_prompt,
                    "image_model": self._config.models.image_model,
                    "video_model": self._config.models.video_model,
                    "image_seed": shot_seed,
                    "image_guidance_scale": self._config.style_consistency.guidance_scale,
                    "image_optimize_prompt": self._config.style_consistency.optimize_prompt,
                    "render_width": self._config.render.width,
                    "render_height": self._config.render.height,
                    "render_fps": self._config.render.fps,
                    "reference_images_used": reference_labels,
                    "character_ids": shot.character_ids,
                    "background_id": shot.background_id,
                },
            )

            try:
                current_stage = "image_generate"
                self._log_event(
                    event="image_generation_started",
                    stage=current_stage,
                    message=f"Generating keyframe image for {shot.shot_id}",
                    shot_id=shot.shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                )
                image_ref = self._generate_image_with_retries(
                    shot_id=shot.shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                    model=self._config.models.image_model,
                    prompt=effective_image_prompt,
                    width=self._config.render.width,
                    height=self._config.render.height,
                    timeout_sec=self._config.generation.request_timeout_sec,
                    reference_images=reference_images,
                    seed=shot_seed,
                    guidance_scale=self._config.style_consistency.guidance_scale,
                    optimize_prompt=self._config.style_consistency.optimize_prompt,
                )
                style_anchor_record["status"] = "keyframe_generated"
                style_anchor_record["image_url"] = image_ref.image_url
                shot_diagnostic.image_url = image_ref.image_url

                current_stage = "keyframe_download"
                keyframe_path = layout.keyframes_dir / f"{shot.shot_id}.png"
                self._asset_store.download_file(
                    source_url=image_ref.image_url,
                    destination=keyframe_path,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                self._log_event(
                    event="keyframe_saved",
                    stage=current_stage,
                    message=f"Saved keyframe to {keyframe_path}",
                    shot_id=shot.shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                )
                shot_diagnostic.keyframe_path = str(keyframe_path)
                style_anchor_record["keyframe_path"] = str(keyframe_path)

                current_stage = "video_task_create"
                task_id = self._video_generator.create_video_task(
                    model=self._config.models.video_model,
                    prompt=effective_video_prompt,
                    image_url=image_ref.image_url,
                    duration_sec=shot.duration_sec,
                    width=self._config.render.width,
                    height=self._config.render.height,
                    fps=self._config.render.fps,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                shot_diagnostic.video_task_id = task_id
                style_anchor_record["video_task_id"] = task_id
                self._log_event(
                    event="video_task_created",
                    stage=current_stage,
                    message=f"Created video task {task_id} for {shot.shot_id}",
                    shot_id=shot.shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                )

                current_stage = "video_task_poll"
                task_status = self._wait_for_video_task(
                    task_id=task_id,
                    shot_id=shot.shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                )
                if not task_status.video_url:
                    raise PipelineExecutionError(
                        f"Video task succeeded but no video_url found for task_id={task_id}"
                    )

                current_stage = "clip_download"
                clip_path = layout.clips_dir / f"{shot.shot_id}.mp4"
                self._asset_store.download_file(
                    source_url=task_status.video_url,
                    destination=clip_path,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                clip_paths.append(clip_path)
                shot_diagnostic.clip_path = str(clip_path)
                style_anchor_record["clip_path"] = str(clip_path)

                records.append(
                    ShotExecutionRecord(
                        shot_id=shot.shot_id,
                        planned_duration_sec=shot.duration_sec,
                        actual_duration_sec=task_status.actual_duration_sec,
                        keyframe_path=str(keyframe_path),
                        image_url=image_ref.image_url,
                        video_task_id=task_id,
                        clip_path=str(clip_path),
                        image_seed=shot_seed,
                        reference_images_used=reference_labels,
                        effective_image_prompt=effective_image_prompt,
                        storyboard_image_prompt=shot.image_prompt,
                        storyboard_video_prompt=shot.video_prompt,
                        effective_video_prompt=effective_video_prompt,
                        image_model=self._config.models.image_model,
                        video_model=self._config.models.video_model,
                        render_width=self._config.render.width,
                        render_height=self._config.render.height,
                        render_fps=self._config.render.fps,
                        image_guidance_scale=self._config.style_consistency.guidance_scale,
                        image_optimize_prompt=self._config.style_consistency.optimize_prompt,
                        character_ids=list(shot.character_ids),
                        background_id=shot.background_id,
                        consistency_references_used=list(reference_labels),
                    )
                )
                previous_successful_references.append(
                    (image_ref.image_url, f"previous_keyframe_{shot.shot_id}")
                )
                previous_successful_shot_id = shot.shot_id
                previous_successful_story_beat = shot.story_beat
                style_anchor_record["status"] = "succeeded"
                shot_diagnostic.status = "succeeded"
                completed_shots += 1
                self._log_event(
                    event="shot_succeeded",
                    stage="shot",
                    message=f"Shot {shot.shot_id} completed successfully",
                    shot_id=shot.shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                    details=self._shot_diagnostics_details(shot_diagnostic),
                )
            except Exception as exc:  # noqa: BLE001
                failed_shots += 1
                error_message = str(exc)
                style_anchor_record["status"] = "failed"
                style_anchor_record["error"] = error_message
                shot_diagnostic.status = "failed"
                shot_diagnostic.failed_stage = current_stage
                shot_diagnostic.error_message = error_message
                failed_records.append(
                    ShotFailureRecord(
                        shot_id=shot.shot_id,
                        stage=current_stage,
                        error_message=error_message,
                    )
                )
                self._log_event(
                    event="shot_failed",
                    stage=current_stage,
                    message=f"Shot {shot.shot_id} failed at stage {current_stage}",
                    level=logging.ERROR,
                    shot_id=shot.shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                    error=error_message,
                    details=self._shot_diagnostics_details(shot_diagnostic),
                )

        style_anchor_manifest_payload = {
            "global_style_lock_text": global_style_lock_text,
            "reference_image_inputs": list(request.reference_image_labels),
            "character_designs": [item.to_dict() for item in character_design_records],
            "background_designs": [item.to_dict() for item in background_design_records],
            "shots": style_anchor_records,
        }
        style_anchor_manifest_path = layout.output_dir / _STYLE_ANCHOR_MANIFEST_FILE
        self._asset_store.write_json(
            file_path=style_anchor_manifest_path,
            payload=style_anchor_manifest_payload,
        )
        self._log_event(
            event="style_anchor_manifest_written",
            stage="style_consistency",
            message=f"Style anchor manifest written to {style_anchor_manifest_path}",
            total_shots=total_shots,
            completed_shots=completed_shots,
            failed_shots=failed_shots,
        )

        merged_video_path = ""
        run_status = "succeeded"
        if failed_records:
            run_status = "partial_failed"
            self._log_event(
                event="merge_skipped",
                stage="merge",
                message="Skipping final merge because one or more shots failed",
                level=logging.WARNING,
                total_shots=total_shots,
                completed_shots=completed_shots,
                failed_shots=failed_shots,
            )
        else:
            self._log_event(
                event="merge_started",
                stage="merge",
                message=f"Merging {len(clip_paths)} clips into final video",
                total_shots=total_shots,
                completed_shots=completed_shots,
                failed_shots=failed_shots,
            )
            self._clip_merger.merge_clips(
                clip_paths=clip_paths,
                output_path=layout.final_video_file,
                width=self._config.render.width,
                height=self._config.render.height,
                fps=self._config.render.fps,
            )
            merged_video_path = str(layout.final_video_file)
            self._log_event(
                event="merge_succeeded",
                stage="merge",
                message=f"Final video generated at {layout.final_video_file}",
                total_shots=total_shots,
                completed_shots=completed_shots,
                failed_shots=failed_shots,
            )

        manifest = RunManifest(
            architecture_contract_version=self._config.architecture_contract_version,
            storyboard_regen_rounds=regen_rounds,
            run_status=run_status,
            total_shots=total_shots,
            succeeded_shots=completed_shots,
            failed_shots=failed_shots,
            offending_shot_history=offending_history,
            character_designs=character_design_records,
            background_designs=background_design_records,
            records=records,
            shot_diagnostics=shot_diagnostics,
            failed_records=failed_records,
            merged_video_path=merged_video_path,
        )
        self._asset_store.write_json(
            file_path=layout.manifest_file,
            payload=manifest.to_dict(),
        )
        self._log_event(
            event="manifest_written",
            stage="run",
            message=f"Run manifest written to {layout.manifest_file}",
            total_shots=total_shots,
            completed_shots=completed_shots,
            failed_shots=failed_shots,
        )
        failed_shot_ids = ", ".join(item.shot_id for item in failed_records) or "none"
        self._log_event(
            event="run_completed",
            stage="run",
            message=(
                f"Run completed with status={run_status}, "
                f"succeeded={completed_shots}, failed={failed_shots}, failed_shots={failed_shot_ids}"
            ),
            level=logging.WARNING if failed_records else logging.INFO,
            total_shots=total_shots,
            completed_shots=completed_shots,
            failed_shots=failed_shots,
        )
        return manifest

    def _extract_main_characters(self, *, outline: str) -> List[CharacterSpec]:
        self._log_event(
            event="character_extraction_started",
            stage="character_extraction",
            message="Extracting main characters from outline",
        )
        prompt = build_character_extraction_prompt(
            outline=outline,
            max_main_characters=self._config.consistency_assets.max_main_characters,
        )
        payload = self._generate_json_payload_from_prompt(
            prompt=prompt,
            stage="character_extraction",
            attempt_started_event="character_extraction_attempt_started",
            attempt_succeeded_event="character_extraction_attempt_succeeded",
            attempt_failed_event="character_extraction_attempt_failed",
            failure_message="Failed to extract character sheet",
        )
        raw_characters = payload.get("characters")
        if not isinstance(raw_characters, list) or not raw_characters:
            raise PipelineExecutionError("Character extraction output must contain non-empty characters list")

        characters = [CharacterSpec.from_dict(item) for item in raw_characters]
        max_characters = max(1, self._config.consistency_assets.max_main_characters)
        characters = characters[:max_characters]
        self._assert_unique_character_ids(characters)

        self._log_event(
            event="character_extraction_succeeded",
            stage="character_extraction",
            message=f"Extracted {len(characters)} characters",
            details={"character_ids": [item.character_id for item in characters]},
        )
        return characters

    def _generate_character_design_assets(
        self,
        *,
        layout: AssetLayout,
        character_specs: Sequence[CharacterSpec],
    ) -> List[DesignAssetRecord]:
        records: List[DesignAssetRecord] = []
        for index, character_spec in enumerate(character_specs, start=1):
            prompt = build_character_design_prompt(
                character_spec=character_spec,
                style_guide=self._config.style_consistency.prompt_lock_preamble,
            )
            record = DesignAssetRecord(
                asset_id=character_spec.character_id,
                asset_type="character",
                prompt=prompt,
                status="in_progress",
            )
            records.append(record)

            self._log_event(
                event="character_design_started",
                stage="character_design",
                message=f"Generating character design {character_spec.character_id} ({index}/{len(character_specs)})",
                details={
                    "character_id": character_spec.character_id,
                    "character_name": character_spec.display_name,
                    "design_prompt": prompt,
                },
            )
            try:
                image_ref = self._generate_design_image_with_retries(
                    asset_type="character",
                    asset_id=character_spec.character_id,
                    prompt=prompt,
                    stage="character_design",
                )
                destination = layout.character_designs_dir / f"{character_spec.character_id}.png"
                self._asset_store.download_file(
                    source_url=image_ref.image_url,
                    destination=destination,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                record.image_url = image_ref.image_url
                record.local_path = str(destination)
                record.status = "succeeded"
                self._log_event(
                    event="character_design_succeeded",
                    stage="character_design",
                    message=f"Character design generated for {character_spec.character_id}",
                    details={
                        "character_id": character_spec.character_id,
                        "image_url": image_ref.image_url,
                        "local_path": str(destination),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                record.status = "failed"
                record.error_message = str(exc)
                self._log_event(
                    event="character_design_failed",
                    stage="character_design",
                    message=f"Character design generation failed for {character_spec.character_id}",
                    level=logging.ERROR,
                    error=str(exc),
                    details={"character_id": character_spec.character_id},
                )
        return records

    def _generate_background_design_assets(
        self,
        *,
        layout: AssetLayout,
        storyboard: Storyboard,
        character_specs: Sequence[CharacterSpec],
    ) -> List[DesignAssetRecord]:
        character_specs_by_id = {item.character_id: item for item in character_specs}
        records: List[DesignAssetRecord] = []
        for index, background_spec in enumerate(storyboard.backgrounds, start=1):
            related_character_ids = self._collect_related_character_ids(
                storyboard_shots=storyboard.shots,
                background_id=background_spec.background_id,
            )
            related_characters = [
                character_specs_by_id[item]
                for item in related_character_ids
                if item in character_specs_by_id
            ]
            prompt = build_background_design_prompt(
                background_spec=background_spec,
                style_guide=storyboard.style_guide,
                related_characters=related_characters,
            )
            record = DesignAssetRecord(
                asset_id=background_spec.background_id,
                asset_type="background",
                prompt=prompt,
                status="in_progress",
            )
            records.append(record)

            self._log_event(
                event="background_design_started",
                stage="background_design",
                message=(
                    f"Generating background design {background_spec.background_id} "
                    f"({index}/{len(storyboard.backgrounds)})"
                ),
                details={
                    "background_id": background_spec.background_id,
                    "background_name": background_spec.display_name,
                    "design_prompt": prompt,
                    "related_character_ids": related_character_ids,
                },
            )
            try:
                image_ref = self._generate_design_image_with_retries(
                    asset_type="background",
                    asset_id=background_spec.background_id,
                    prompt=prompt,
                    stage="background_design",
                )
                destination = layout.background_designs_dir / f"{background_spec.background_id}.png"
                self._asset_store.download_file(
                    source_url=image_ref.image_url,
                    destination=destination,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                record.image_url = image_ref.image_url
                record.local_path = str(destination)
                record.status = "succeeded"
                self._log_event(
                    event="background_design_succeeded",
                    stage="background_design",
                    message=f"Background design generated for {background_spec.background_id}",
                    details={
                        "background_id": background_spec.background_id,
                        "image_url": image_ref.image_url,
                        "local_path": str(destination),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                record.status = "failed"
                record.error_message = str(exc)
                self._log_event(
                    event="background_design_failed",
                    stage="background_design",
                    message=f"Background design generation failed for {background_spec.background_id}",
                    level=logging.ERROR,
                    error=str(exc),
                    details={"background_id": background_spec.background_id},
                )
        return records

    def _enforce_required_design_assets(
        self,
        *,
        records: Sequence[DesignAssetRecord],
        stage: str,
        asset_type: str,
    ) -> None:
        failed_ids = [item.asset_id for item in records if item.status != "succeeded" or not item.image_url]
        if not failed_ids:
            return

        self._log_event(
            event=f"{asset_type}_design_assets_incomplete",
            stage=stage,
            message=f"{asset_type.capitalize()} design assets incomplete: {failed_ids}",
            level=logging.WARNING,
            details={"failed_asset_ids": failed_ids},
        )
        if self._config.consistency_assets.fail_on_missing_design_assets:
            raise PipelineExecutionError(
                f"Required {asset_type} design assets are missing: {failed_ids}"
            )

    def _generate_storyboard_with_regeneration(
        self,
        *,
        outline: str,
        character_specs: Sequence[CharacterSpec],
    ) -> Tuple[Storyboard, int, List[List[dict]]]:
        allowed_character_ids = [item.character_id for item in character_specs]
        self._log_event(
            event="storyboard_generation_started",
            stage="storyboard",
            message="Generating storyboard from outline",
            details={"character_ids": allowed_character_ids},
        )

        initial_prompt = build_storyboard_prompt(
            outline=outline,
            max_shot_duration_sec=self._config.storyboard.max_shot_duration_sec,
            character_specs=character_specs,
            max_backgrounds=self._config.consistency_assets.max_backgrounds,
        )
        storyboard = self._generate_storyboard_from_prompt(
            prompt=initial_prompt,
            allowed_character_ids=allowed_character_ids,
        )

        offending_history: List[List[dict]] = []

        for regen_round in range(self._config.storyboard.max_regen_rounds + 1):
            validation = validate_storyboard(
                storyboard,
                max_shot_duration_sec=self._config.storyboard.max_shot_duration_sec,
                regen_round=regen_round,
            )
            self._log_event(
                event="storyboard_validation_round",
                stage="storyboard_validation",
                message=(
                    f"Storyboard validation round {regen_round}: "
                    f"offending_shots={len(validation.offending_shots)}"
                ),
            )
            if not validation.offending_shots:
                return storyboard, regen_round, offending_history

            offending_history.append([shot.to_dict() for shot in validation.offending_shots])
            if regen_round >= self._config.storyboard.max_regen_rounds:
                raise StoryboardRegenerationError(
                    "Storyboard still contains overlong shots after maximum regeneration rounds: "
                    f"{validation.offending_shots}"
                )

            regeneration_prompt = build_storyboard_regeneration_prompt(
                outline=outline,
                current_storyboard=storyboard,
                offending_shots=validation.offending_shots,
                max_shot_duration_sec=self._config.storyboard.max_shot_duration_sec,
            )
            self._log_event(
                event="storyboard_regeneration_started",
                stage="storyboard_regeneration",
                message=(
                    "Regenerating offending shots: "
                    f"{[shot.shot_id for shot in validation.offending_shots]}"
                ),
            )
            regenerated_storyboard = self._generate_storyboard_from_prompt(
                prompt=regeneration_prompt,
                allowed_character_ids=allowed_character_ids,
            )
            storyboard = merge_storyboard_with_regenerated_shots(
                current_storyboard=storyboard,
                regenerated_storyboard=regenerated_storyboard,
                offending_shot_ids=[shot.shot_id for shot in validation.offending_shots],
            )
            validate_storyboard_references(
                storyboard=storyboard,
                allowed_character_ids=allowed_character_ids,
            )

        raise StoryboardRegenerationError("Unexpected storyboard regeneration flow")

    def _generate_storyboard_from_prompt(
        self,
        *,
        prompt: str,
        allowed_character_ids: Sequence[str],
    ) -> Storyboard:
        last_error: Exception | None = None
        attempts = self._config.generation.text_max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                self._log_event(
                    event="storyboard_model_attempt_started",
                    stage="storyboard_model",
                    message=f"Storyboard model attempt {attempt}/{attempts}",
                )
                raw_output = self._storyboard_model.generate_storyboard(
                    model=self._config.models.storyboard_text_model,
                    prompt=prompt,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                storyboard = parse_storyboard(raw_output)
                validate_storyboard_references(
                    storyboard=storyboard,
                    allowed_character_ids=allowed_character_ids,
                )
                self._log_event(
                    event="storyboard_model_attempt_succeeded",
                    stage="storyboard_model",
                    message=f"Storyboard model attempt {attempt}/{attempts} succeeded",
                )
                return storyboard
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._log_event(
                    event="storyboard_model_attempt_failed",
                    stage="storyboard_model",
                    message=f"Storyboard model attempt {attempt}/{attempts} failed",
                    level=logging.WARNING,
                    error=str(exc),
                )
        raise PipelineExecutionError(
            f"Failed to generate valid storyboard after {attempts} attempts"
        ) from last_error

    def _generate_json_payload_from_prompt(
        self,
        *,
        prompt: str,
        stage: str,
        attempt_started_event: str,
        attempt_succeeded_event: str,
        attempt_failed_event: str,
        failure_message: str,
    ) -> dict:
        last_error: Exception | None = None
        attempts = self._config.generation.text_max_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                self._log_event(
                    event=attempt_started_event,
                    stage=stage,
                    message=f"{stage} model attempt {attempt}/{attempts}",
                )
                raw_output = self._storyboard_model.generate_storyboard(
                    model=self._config.models.storyboard_text_model,
                    prompt=prompt,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                payload = self._parse_json_object(raw_output)
                self._log_event(
                    event=attempt_succeeded_event,
                    stage=stage,
                    message=f"{stage} model attempt {attempt}/{attempts} succeeded",
                )
                return payload
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._log_event(
                    event=attempt_failed_event,
                    stage=stage,
                    message=f"{stage} model attempt {attempt}/{attempts} failed",
                    level=logging.WARNING,
                    error=str(exc),
                )
        raise PipelineExecutionError(f"{failure_message} after {attempts} attempts") from last_error

    @staticmethod
    def _parse_json_object(raw_text: str) -> dict:
        cleaned = raw_text.strip()
        if not cleaned:
            raise PipelineExecutionError("Model output is empty")

        match = re.search(r"```(?:json)?\\s*(\{.*\})\\s*```", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)
        elif not (cleaned.startswith("{") and cleaned.endswith("}")):
            first = cleaned.find("{")
            last = cleaned.rfind("}")
            if first == -1 or last == -1 or first >= last:
                raise PipelineExecutionError("Model output does not contain JSON object")
            cleaned = cleaned[first : last + 1]

        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise PipelineExecutionError("Model JSON output must be an object")
        return payload

    def _wait_for_video_task(
        self,
        *,
        task_id: str,
        shot_id: str,
        shot_index: int,
        total_shots: int,
        completed_shots: int,
        failed_shots: int,
    ) -> VideoTaskStatus:
        for poll_count in range(1, self._config.generation.task_max_polls + 1):
            status = self._video_generator.get_video_task_status(
                task_id=task_id,
                timeout_sec=self._config.generation.request_timeout_sec,
            )
            if poll_count == 1 or poll_count % 10 == 0:
                self._log_event(
                    event="video_task_polling",
                    stage="video_task_poll",
                    message=(
                        f"Polling task {task_id} for {shot_id}: "
                        f"poll={poll_count}, status={status.status}"
                    ),
                    shot_id=shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                )
            normalized = status.status.strip().lower()
            if normalized in _SUCCEEDED_STATUSES:
                self._log_event(
                    event="video_task_succeeded",
                    stage="video_task_poll",
                    message=f"Video task {task_id} succeeded for {shot_id}",
                    shot_id=shot_id,
                    shot_index=shot_index,
                    total_shots=total_shots,
                    completed_shots=completed_shots,
                    failed_shots=failed_shots,
                )
                return status
            if normalized in _FAILED_STATUSES:
                raise PipelineExecutionError(
                    f"Video task failed: task_id={task_id}, status={status.status}, "
                    f"error={status.error_message}"
                )
            time.sleep(self._config.generation.task_poll_interval_sec)

        raise PipelineExecutionError(
            f"Video task polling exceeded max polls for task_id={task_id}"
        )

    def _select_reference_images(
        self,
        *,
        shot: Shot,
        character_design_refs: Dict[str, Tuple[str, str]],
        background_design_refs: Dict[str, Tuple[str, str]],
        user_reference_images: Sequence[str],
        user_reference_labels: Sequence[str],
        previous_successful_references: Sequence[Tuple[str, str]],
    ) -> Tuple[List[str], List[str]]:
        selected: List[Tuple[str, str]] = []
        seen_pairs: set[Tuple[str, str]] = set()

        def add_reference(url: str, label: str) -> None:
            key = (url, label)
            if not url or key in seen_pairs:
                return
            selected.append((url, label))
            seen_pairs.add(key)

        character_limit = max(0, self._config.consistency_assets.max_character_refs_per_shot)
        selected_character_count = 0
        for character_id in shot.character_ids:
            if character_limit > 0 and selected_character_count >= character_limit:
                break
            item = character_design_refs.get(character_id)
            if not item:
                continue
            add_reference(item[0], item[1])
            selected_character_count += 1

        background_item = background_design_refs.get(shot.background_id)
        if background_item:
            add_reference(background_item[0], background_item[1])

        for index, ref in enumerate(user_reference_images):
            label = (
                user_reference_labels[index]
                if index < len(user_reference_labels)
                else f"user_reference_{index + 1}"
            )
            add_reference(ref, label)

        carryover = max(0, self._config.style_consistency.carryover_prev_keyframes)
        if carryover > 0 and previous_successful_references:
            for ref_url, ref_label in list(previous_successful_references)[-carryover:]:
                add_reference(ref_url, ref_label)

        max_refs = max(0, self._config.style_consistency.max_reference_images_per_shot)
        if max_refs > 0:
            selected = selected[:max_refs]
        else:
            selected = []

        return [item[0] for item in selected], [item[1] for item in selected]

    def _generate_design_image_with_retries(
        self,
        *,
        asset_type: str,
        asset_id: str,
        prompt: str,
        stage: str,
    ):
        attempts = 1 + max(0, self._config.style_consistency.retry_on_image_generation_error)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1:
                    self._log_event(
                        event=f"{asset_type}_design_retry",
                        stage=stage,
                        message=(
                            f"Retry {asset_type} design image generation for {asset_id}, "
                            f"attempt {attempt}/{attempts}"
                        ),
                        level=logging.WARNING,
                    )
                return self._image_generator.generate_image(
                    model=self._config.models.image_model,
                    prompt=prompt,
                    width=self._config.render.width,
                    height=self._config.render.height,
                    timeout_sec=self._config.generation.request_timeout_sec,
                    reference_images=[],
                    seed=None,
                    guidance_scale=self._config.style_consistency.guidance_scale,
                    optimize_prompt=self._config.style_consistency.optimize_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc

        raise PipelineExecutionError(
            f"{asset_type.capitalize()} design image generation failed after {attempts} "
            f"attempts for asset_id={asset_id}"
        ) from last_error

    def _generate_image_with_retries(
        self,
        *,
        shot_id: str,
        shot_index: int,
        total_shots: int,
        completed_shots: int,
        failed_shots: int,
        model: str,
        prompt: str,
        width: int,
        height: int,
        timeout_sec: int,
        reference_images: Sequence[str],
        seed: int | None,
        guidance_scale: float | None,
        optimize_prompt: bool | None,
    ):
        attempts = 1 + max(0, self._config.style_consistency.retry_on_image_generation_error)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1:
                    self._log_event(
                        event="image_generation_retry",
                        stage="image_generate",
                        message=f"Retry image generation for {shot_id}, attempt {attempt}/{attempts}",
                        level=logging.WARNING,
                        shot_id=shot_id,
                        shot_index=shot_index,
                        total_shots=total_shots,
                        completed_shots=completed_shots,
                        failed_shots=failed_shots,
                    )
                return self._image_generator.generate_image(
                    model=model,
                    prompt=prompt,
                    width=width,
                    height=height,
                    timeout_sec=timeout_sec,
                    reference_images=reference_images,
                    seed=seed,
                    guidance_scale=guidance_scale,
                    optimize_prompt=optimize_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        raise PipelineExecutionError(
            f"Image generation failed after {attempts} attempts for shot_id={shot_id}"
        ) from last_error

    @staticmethod
    def _build_character_context(character_specs: Sequence[CharacterSpec]) -> str:
        if not character_specs:
            return "No explicit character context available."
        lines = []
        for item in character_specs:
            display_name = item.display_name or item.character_id
            lines.append(
                f"- {item.character_id} ({display_name}): {item.identity_description}; "
                f"design intent: {item.design_prompt}"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_background_context(background_spec: BackgroundSpec | None) -> str:
        if background_spec is None:
            return "No explicit background context available."
        display_name = background_spec.display_name or background_spec.background_id
        return (
            f"- {background_spec.background_id} ({display_name}): "
            f"{background_spec.location_description}; constraints: {background_spec.visual_constraints}; "
            f"design intent: {background_spec.design_prompt}"
        )

    @staticmethod
    def _collect_related_character_ids(
        *,
        storyboard_shots: Iterable[Shot],
        background_id: str,
    ) -> List[str]:
        seen: set[str] = set()
        ordered: List[str] = []
        for shot in storyboard_shots:
            if shot.background_id != background_id:
                continue
            for char_id in shot.character_ids:
                if char_id in seen:
                    continue
                seen.add(char_id)
                ordered.append(char_id)
        return ordered

    @staticmethod
    def _assert_unique_character_ids(characters: Sequence[CharacterSpec]) -> None:
        seen: set[str] = set()
        for item in characters:
            character_id = item.character_id.strip()
            if not character_id:
                raise PipelineExecutionError("character_id cannot be empty")
            if character_id in seen:
                raise PipelineExecutionError(f"Duplicate character_id found: {character_id}")
            seen.add(character_id)

    def _log_event(
        self,
        *,
        event: str,
        stage: str,
        message: str,
        level: int = logging.INFO,
        shot_id: str | None = None,
        shot_index: int | None = None,
        total_shots: int = 0,
        completed_shots: int = 0,
        failed_shots: int = 0,
        error: str | None = None,
        details: dict | None = None,
    ) -> None:
        self._logger.log(
            level,
            message,
            extra={
                "event": event,
                "stage": stage,
                "shot_id": shot_id,
                "shot_index": shot_index,
                "total_shots": total_shots,
                "completed_shots": completed_shots,
                "failed_shots": failed_shots,
                "error": error,
                "details": details,
            },
        )

    @staticmethod
    def _shot_diagnostics_details(record: ShotDiagnosticsRecord) -> Dict[str, object]:
        return record.to_dict()
