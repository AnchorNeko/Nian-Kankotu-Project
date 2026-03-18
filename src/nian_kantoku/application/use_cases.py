from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from nian_kantoku.application.config import AppConfig
from nian_kantoku.application.ports import (
    AssetStorePort,
    ClipMergerPort,
    ImageGeneratorPort,
    RuntimeDependencyPort,
    StoryboardModelPort,
    VideoGeneratorPort,
)
from nian_kantoku.application.run_models import (
    DesignAssetSummary,
    RunArtifacts,
    RunManifest,
)
from nian_kantoku.application.services.design_asset_service import DesignAssetService
from nian_kantoku.application.services.shot_execution_service import ShotExecutionService
from nian_kantoku.application.services.storyboard_service import StoryboardService


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
        self._asset_store = asset_store
        self._clip_merger = clip_merger
        self._runtime_dependency = runtime_dependency
        self._logger = logging.getLogger("nian_kantoku.run")

        self._storyboard_service = StoryboardService(
            config=config,
            storyboard_model=storyboard_model,
            log_event=self._log_event,
        )
        self._design_asset_service = DesignAssetService(
            config=config,
            image_generator=image_generator,
            asset_store=asset_store,
            log_event=self._log_event,
        )
        self._shot_execution_service = ShotExecutionService(
            config=config,
            image_generator=image_generator,
            video_generator=video_generator,
            asset_store=asset_store,
            log_event=self._log_event,
        )

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
            shot_diagnostics_file_name=self._config.paths.shot_diagnostics_file,
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

        character_specs = self._storyboard_service.extract_main_characters(outline=outline)
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

        character_design_records = self._design_asset_service.generate_character_design_assets(
            layout=layout,
            character_specs=character_specs,
        )
        self._design_asset_service.enforce_required_design_assets(
            records=character_design_records,
            stage="character_design",
            asset_type="character",
        )

        storyboard, regen_rounds, offending_history = (
            self._storyboard_service.generate_storyboard_with_regeneration(
                outline=outline,
                character_specs=character_specs,
            )
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

        background_design_records = self._design_asset_service.generate_background_design_assets(
            layout=layout,
            storyboard=storyboard,
            character_specs=character_specs,
        )
        self._design_asset_service.enforce_required_design_assets(
            records=background_design_records,
            stage="background_design",
            asset_type="background",
        )

        shot_result = self._shot_execution_service.execute_shots(
            layout=layout,
            storyboard=storyboard,
            character_specs=character_specs,
            character_design_records=character_design_records,
            background_design_records=background_design_records,
            user_reference_images=request.reference_images,
            user_reference_labels=request.reference_image_labels,
        )

        self._asset_store.write_jsonl(
            file_path=layout.shot_diagnostics_file,
            payloads=[item.to_dict() for item in shot_result.diagnostics],
        )
        self._log_event(
            event="shot_diagnostics_written",
            stage="run",
            message=f"Shot diagnostics written to {layout.shot_diagnostics_file}",
            total_shots=total_shots,
            completed_shots=shot_result.completed_shots,
            failed_shots=shot_result.failed_shots,
        )

        merged_video_path = ""
        run_status = "succeeded"
        if shot_result.failed_shot_ids:
            run_status = "partial_failed"
            self._log_event(
                event="merge_skipped",
                stage="merge",
                message="Skipping final merge because one or more shots failed",
                level=logging.WARNING,
                total_shots=total_shots,
                completed_shots=shot_result.completed_shots,
                failed_shots=shot_result.failed_shots,
            )
        else:
            self._log_event(
                event="merge_started",
                stage="merge",
                message=f"Merging {len(shot_result.clip_paths)} clips into final video",
                total_shots=total_shots,
                completed_shots=shot_result.completed_shots,
                failed_shots=shot_result.failed_shots,
            )
            self._clip_merger.merge_clips(
                clip_paths=shot_result.clip_paths,
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
                completed_shots=shot_result.completed_shots,
                failed_shots=shot_result.failed_shots,
            )

        manifest = RunManifest(
            architecture_contract_version=self._config.architecture_contract_version,
            storyboard_regen_rounds=regen_rounds,
            run_status=run_status,
            total_shots=total_shots,
            succeeded_shots=shot_result.completed_shots,
            failed_shots=shot_result.failed_shots,
            failed_shot_ids=list(shot_result.failed_shot_ids),
            offending_shot_history=offending_history,
            character_design_summary=self._build_design_summary(character_design_records),
            background_design_summary=self._build_design_summary(background_design_records),
            merged_video_path=merged_video_path,
            artifacts=RunArtifacts(
                character_sheet_file=str(layout.character_sheet_file),
                background_sheet_file=str(layout.background_sheet_file),
                storyboard_file=str(layout.storyboard_file),
                character_designs_dir=str(layout.character_designs_dir),
                background_designs_dir=str(layout.background_designs_dir),
                keyframes_dir=str(layout.keyframes_dir),
                clips_dir=str(layout.clips_dir),
                shot_diagnostics_file=str(layout.shot_diagnostics_file),
            ),
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
            completed_shots=shot_result.completed_shots,
            failed_shots=shot_result.failed_shots,
        )
        failed_shot_ids = ", ".join(shot_result.failed_shot_ids) or "none"
        self._log_event(
            event="run_completed",
            stage="run",
            message=(
                f"Run completed with status={run_status}, "
                f"succeeded={shot_result.completed_shots}, "
                f"failed={shot_result.failed_shots}, "
                f"failed_shots={failed_shot_ids}"
            ),
            level=logging.WARNING if shot_result.failed_shot_ids else logging.INFO,
            total_shots=total_shots,
            completed_shots=shot_result.completed_shots,
            failed_shots=shot_result.failed_shots,
        )
        return manifest

    @staticmethod
    def _build_design_summary(records) -> DesignAssetSummary:
        total = len(records)
        succeeded = sum(1 for item in records if item.status == "succeeded")
        failed_asset_ids = [item.asset_id for item in records if item.status != "succeeded"]
        return DesignAssetSummary(
            total=total,
            succeeded=succeeded,
            failed=total - succeeded,
            failed_asset_ids=failed_asset_ids,
        )

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
