from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Sequence, Tuple

from nian_kantoku.application.config import AppConfig
from nian_kantoku.application.exceptions import PipelineExecutionError
from nian_kantoku.application.ports import AssetStorePort, ImageGeneratorPort, VideoGeneratorPort
from nian_kantoku.application.prompt_templates import (
    build_anti_drift_constraints,
    build_effective_image_prompt,
    build_effective_video_prompt,
    build_global_style_lock_text,
    build_shot_continuity_lock_text,
)
from nian_kantoku.application.run_models import (
    AssetLayout,
    DesignAssetRecord,
    ShotDiagnosticsRecord,
    VideoTaskStatus,
)
from nian_kantoku.domain.models import BackgroundSpec, CharacterSpec, Shot, Storyboard


_SUCCEEDED_STATUSES = {"succeeded", "success", "completed", "done"}
_FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "rejected", "timeout"}

LogEvent = Callable[..., None]


@dataclass
class ShotExecutionResult:
    diagnostics: List[ShotDiagnosticsRecord]
    failed_shot_ids: List[str]
    clip_paths: List[Path]
    completed_shots: int
    failed_shots: int


class ShotExecutionService:
    def __init__(
        self,
        *,
        config: AppConfig,
        image_generator: ImageGeneratorPort,
        video_generator: VideoGeneratorPort,
        asset_store: AssetStorePort,
        log_event: LogEvent,
    ) -> None:
        self._config = config
        self._image_generator = image_generator
        self._video_generator = video_generator
        self._asset_store = asset_store
        self._log_event = log_event

    def execute_shots(
        self,
        *,
        layout: AssetLayout,
        storyboard: Storyboard,
        character_specs: Sequence[CharacterSpec],
        character_design_records: Sequence[DesignAssetRecord],
        background_design_records: Sequence[DesignAssetRecord],
        user_reference_images: Sequence[str],
        user_reference_labels: Sequence[str],
    ) -> ShotExecutionResult:
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

        diagnostics: List[ShotDiagnosticsRecord] = []
        clip_paths: List[Path] = []
        failed_shot_ids: List[str] = []
        completed_shots = 0
        failed_shots = 0
        previous_successful_references: List[Tuple[str, str]] = []
        previous_successful_shot_id: str | None = None
        previous_successful_story_beat: str | None = None
        total_shots = len(storyboard.shots)

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
                user_reference_images=user_reference_images,
                user_reference_labels=user_reference_labels,
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
            diagnostics.append(shot_diagnostic)

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
                details=shot_diagnostic.to_dict(),
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
                    reference_images=reference_images,
                    seed=shot_seed,
                    guidance_scale=self._config.style_consistency.guidance_scale,
                    optimize_prompt=self._config.style_consistency.optimize_prompt,
                )
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

                current_stage = "video_task_create"
                task_id = self._video_generator.create_video_task(
                    model=self._config.models.video_model,
                    prompt=effective_video_prompt,
                    image_url=image_ref.image_url,
                )
                shot_diagnostic.video_task_id = task_id
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

                previous_successful_references.append(
                    (image_ref.image_url, f"previous_keyframe_{shot.shot_id}")
                )
                previous_successful_shot_id = shot.shot_id
                previous_successful_story_beat = shot.story_beat
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
                    details=shot_diagnostic.to_dict(),
                )
            except Exception as exc:  # noqa: BLE001
                failed_shots += 1
                error_message = str(exc)
                shot_diagnostic.status = "failed"
                shot_diagnostic.failed_stage = current_stage
                shot_diagnostic.error_message = error_message
                failed_shot_ids.append(shot.shot_id)
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
                    details=shot_diagnostic.to_dict(),
                )

        return ShotExecutionResult(
            diagnostics=diagnostics,
            failed_shot_ids=failed_shot_ids,
            clip_paths=clip_paths,
            completed_shots=completed_shots,
            failed_shots=failed_shots,
        )

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
            status = self._video_generator.get_video_task_status(task_id=task_id)
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
