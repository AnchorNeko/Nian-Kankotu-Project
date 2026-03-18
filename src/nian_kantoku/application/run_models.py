from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class GeneratedImageReference:
    image_url: str


@dataclass
class VideoTaskStatus:
    task_id: str
    status: str
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    actual_duration_sec: Optional[float] = None


@dataclass
class AssetLayout:
    output_dir: Path
    keyframes_dir: Path
    clips_dir: Path
    character_designs_dir: Path
    background_designs_dir: Path
    character_sheet_file: Path
    background_sheet_file: Path
    storyboard_file: Path
    shot_diagnostics_file: Path
    final_video_file: Path
    manifest_file: Path


@dataclass
class DesignAssetRecord:
    asset_id: str
    asset_type: str
    prompt: str
    image_url: str = ""
    local_path: str = ""
    status: str = "pending"
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_type": self.asset_type,
            "prompt": self.prompt,
            "image_url": self.image_url,
            "local_path": self.local_path,
            "status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class ShotDiagnosticsRecord:
    shot_id: str
    shot_index: int
    status: str
    planned_duration_sec: float
    storyboard_image_prompt: str = ""
    storyboard_video_prompt: str = ""
    effective_image_prompt: str = ""
    effective_video_prompt: str = ""
    image_model: str = ""
    video_model: str = ""
    image_seed: Optional[int] = None
    image_guidance_scale: Optional[float] = None
    image_optimize_prompt: Optional[bool] = None
    render_width: Optional[int] = None
    render_height: Optional[int] = None
    render_fps: Optional[int] = None
    reference_images_used: List[str] = field(default_factory=list)
    keyframe_path: str = ""
    image_url: str = ""
    video_task_id: str = ""
    clip_path: str = ""
    character_ids: List[str] = field(default_factory=list)
    background_id: str = ""
    consistency_references_used: List[str] = field(default_factory=list)
    failed_stage: str = ""
    error_message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "shot_index": self.shot_index,
            "status": self.status,
            "planned_duration_sec": self.planned_duration_sec,
            "storyboard_image_prompt": self.storyboard_image_prompt,
            "storyboard_video_prompt": self.storyboard_video_prompt,
            "effective_image_prompt": self.effective_image_prompt,
            "effective_video_prompt": self.effective_video_prompt,
            "image_model": self.image_model,
            "video_model": self.video_model,
            "image_seed": self.image_seed,
            "image_guidance_scale": self.image_guidance_scale,
            "image_optimize_prompt": self.image_optimize_prompt,
            "render_width": self.render_width,
            "render_height": self.render_height,
            "render_fps": self.render_fps,
            "reference_images_used": self.reference_images_used,
            "keyframe_path": self.keyframe_path,
            "image_url": self.image_url,
            "video_task_id": self.video_task_id,
            "clip_path": self.clip_path,
            "character_ids": self.character_ids,
            "background_id": self.background_id,
            "consistency_references_used": self.consistency_references_used,
            "failed_stage": self.failed_stage,
            "error_message": self.error_message,
        }


@dataclass
class DesignAssetSummary:
    total: int
    succeeded: int
    failed: int
    failed_asset_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total": self.total,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "failed_asset_ids": self.failed_asset_ids,
        }


@dataclass
class RunArtifacts:
    character_sheet_file: str
    background_sheet_file: str
    storyboard_file: str
    character_designs_dir: str
    background_designs_dir: str
    keyframes_dir: str
    clips_dir: str
    shot_diagnostics_file: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_sheet_file": self.character_sheet_file,
            "background_sheet_file": self.background_sheet_file,
            "storyboard_file": self.storyboard_file,
            "character_designs_dir": self.character_designs_dir,
            "background_designs_dir": self.background_designs_dir,
            "keyframes_dir": self.keyframes_dir,
            "clips_dir": self.clips_dir,
            "shot_diagnostics_file": self.shot_diagnostics_file,
        }


@dataclass
class RunManifest:
    architecture_contract_version: str
    storyboard_regen_rounds: int
    run_status: str
    total_shots: int
    succeeded_shots: int
    failed_shots: int
    failed_shot_ids: List[str]
    offending_shot_history: List[List[Dict[str, Any]]]
    character_design_summary: DesignAssetSummary
    background_design_summary: DesignAssetSummary
    merged_video_path: str
    artifacts: RunArtifacts

    def to_dict(self) -> Dict[str, Any]:
        return {
            "architecture_contract_version": self.architecture_contract_version,
            "storyboard_regen_rounds": self.storyboard_regen_rounds,
            "run_status": self.run_status,
            "total_shots": self.total_shots,
            "succeeded_shots": self.succeeded_shots,
            "failed_shots": self.failed_shots,
            "failed_shot_ids": self.failed_shot_ids,
            "offending_shot_history": self.offending_shot_history,
            "character_design_summary": self.character_design_summary.to_dict(),
            "background_design_summary": self.background_design_summary.to_dict(),
            "merged_video_path": self.merged_video_path,
            "artifacts": self.artifacts.to_dict(),
        }
