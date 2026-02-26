from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class CharacterSpec:
    character_id: str
    display_name: str
    identity_description: str
    design_prompt: str

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "CharacterSpec":
        return cls(
            character_id=str(payload["character_id"]),
            display_name=str(payload.get("display_name", "")),
            identity_description=str(payload.get("identity_description", "")),
            design_prompt=str(payload.get("design_prompt", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "character_id": self.character_id,
            "display_name": self.display_name,
            "identity_description": self.identity_description,
            "design_prompt": self.design_prompt,
        }


@dataclass
class BackgroundSpec:
    background_id: str
    display_name: str
    location_description: str
    visual_constraints: str
    design_prompt: str

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "BackgroundSpec":
        return cls(
            background_id=str(payload["background_id"]),
            display_name=str(payload.get("display_name", "")),
            location_description=str(payload.get("location_description", "")),
            visual_constraints=str(payload.get("visual_constraints", "")),
            design_prompt=str(payload.get("design_prompt", "")),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "background_id": self.background_id,
            "display_name": self.display_name,
            "location_description": self.location_description,
            "visual_constraints": self.visual_constraints,
            "design_prompt": self.design_prompt,
        }


@dataclass
class Shot:
    shot_id: str
    duration_sec: float
    story_beat: str
    camera_instruction: str
    image_prompt: str
    video_prompt: str
    character_ids: List[str] = field(default_factory=list)
    background_id: str = ""

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Shot":
        raw_character_ids = payload.get("character_ids")
        if not isinstance(raw_character_ids, list) or not raw_character_ids:
            raise ValueError("Shot must include non-empty character_ids list")
        character_ids = [str(item).strip() for item in raw_character_ids if str(item).strip()]
        if not character_ids:
            raise ValueError("Shot character_ids cannot be empty")

        background_id = str(payload.get("background_id", "")).strip()
        if not background_id:
            raise ValueError("Shot must include background_id")

        return cls(
            shot_id=str(payload["shot_id"]),
            duration_sec=float(payload["duration_sec"]),
            story_beat=str(payload.get("story_beat", "")),
            camera_instruction=str(payload.get("camera_instruction", "")),
            image_prompt=str(payload.get("image_prompt", "")),
            video_prompt=str(payload.get("video_prompt", "")),
            character_ids=character_ids,
            background_id=background_id,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "duration_sec": self.duration_sec,
            "story_beat": self.story_beat,
            "camera_instruction": self.camera_instruction,
            "image_prompt": self.image_prompt,
            "video_prompt": self.video_prompt,
            "character_ids": self.character_ids,
            "background_id": self.background_id,
        }


@dataclass
class Storyboard:
    shots: List[Shot]
    backgrounds: List[BackgroundSpec] = field(default_factory=list)
    style_guide: str = ""
    total_planned_duration: float = 0.0

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "Storyboard":
        raw_shots = payload.get("shots")
        if not isinstance(raw_shots, list) or not raw_shots:
            raise ValueError("Storyboard must include a non-empty shots list")

        shots = [Shot.from_dict(item) for item in raw_shots]
        raw_backgrounds = payload.get("backgrounds")
        if not isinstance(raw_backgrounds, list) or not raw_backgrounds:
            raise ValueError("Storyboard must include a non-empty backgrounds list")
        backgrounds = [BackgroundSpec.from_dict(item) for item in raw_backgrounds]
        total_duration = payload.get("total_planned_duration")
        if total_duration is None:
            total_duration = sum(shot.duration_sec for shot in shots)

        return cls(
            shots=shots,
            backgrounds=backgrounds,
            style_guide=str(payload.get("style_guide", "")),
            total_planned_duration=float(total_duration),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shots": [shot.to_dict() for shot in self.shots],
            "backgrounds": [background.to_dict() for background in self.backgrounds],
            "style_guide": self.style_guide,
            "total_planned_duration": self.total_planned_duration,
        }


@dataclass
class OffendingShot:
    shot_id: str
    duration_sec: float
    reason: str = "duration_exceeds_limit"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "duration_sec": self.duration_sec,
            "reason": self.reason,
        }


@dataclass
class StoryboardValidationResult:
    valid_shots: List[Shot]
    offending_shots: List[OffendingShot]
    regen_round: int


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
class ShotExecutionRecord:
    shot_id: str
    planned_duration_sec: float
    actual_duration_sec: Optional[float]
    keyframe_path: str
    image_url: str
    video_task_id: str
    clip_path: str
    image_seed: Optional[int] = None
    reference_images_used: List[str] = field(default_factory=list)
    effective_image_prompt: str = ""
    storyboard_image_prompt: str = ""
    storyboard_video_prompt: str = ""
    effective_video_prompt: str = ""
    image_model: str = ""
    video_model: str = ""
    render_width: Optional[int] = None
    render_height: Optional[int] = None
    render_fps: Optional[int] = None
    image_guidance_scale: Optional[float] = None
    image_optimize_prompt: Optional[bool] = None
    character_ids: List[str] = field(default_factory=list)
    background_id: str = ""
    consistency_references_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "planned_duration_sec": self.planned_duration_sec,
            "actual_duration_sec": self.actual_duration_sec,
            "keyframe_path": self.keyframe_path,
            "image_url": self.image_url,
            "video_task_id": self.video_task_id,
            "clip_path": self.clip_path,
            "image_seed": self.image_seed,
            "reference_images_used": self.reference_images_used,
            "effective_image_prompt": self.effective_image_prompt,
            "storyboard_image_prompt": self.storyboard_image_prompt,
            "storyboard_video_prompt": self.storyboard_video_prompt,
            "effective_video_prompt": self.effective_video_prompt,
            "image_model": self.image_model,
            "video_model": self.video_model,
            "render_width": self.render_width,
            "render_height": self.render_height,
            "render_fps": self.render_fps,
            "image_guidance_scale": self.image_guidance_scale,
            "image_optimize_prompt": self.image_optimize_prompt,
            "character_ids": self.character_ids,
            "background_id": self.background_id,
            "consistency_references_used": self.consistency_references_used,
        }


@dataclass
class ShotFailureRecord:
    shot_id: str
    stage: str
    error_message: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot_id": self.shot_id,
            "stage": self.stage,
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
class RunManifest:
    architecture_contract_version: str
    storyboard_regen_rounds: int
    run_status: str = "succeeded"
    total_shots: int = 0
    succeeded_shots: int = 0
    failed_shots: int = 0
    offending_shot_history: List[List[Dict[str, Any]]] = field(default_factory=list)
    character_designs: List[DesignAssetRecord] = field(default_factory=list)
    background_designs: List[DesignAssetRecord] = field(default_factory=list)
    records: List[ShotExecutionRecord] = field(default_factory=list)
    shot_diagnostics: List[ShotDiagnosticsRecord] = field(default_factory=list)
    failed_records: List[ShotFailureRecord] = field(default_factory=list)
    merged_video_path: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "architecture_contract_version": self.architecture_contract_version,
            "storyboard_regen_rounds": self.storyboard_regen_rounds,
            "run_status": self.run_status,
            "total_shots": self.total_shots,
            "succeeded_shots": self.succeeded_shots,
            "failed_shots": self.failed_shots,
            "offending_shot_history": self.offending_shot_history,
            "character_designs": [record.to_dict() for record in self.character_designs],
            "background_designs": [record.to_dict() for record in self.background_designs],
            "records": [record.to_dict() for record in self.records],
            "shot_diagnostics": [record.to_dict() for record in self.shot_diagnostics],
            "failed_records": [record.to_dict() for record in self.failed_records],
            "merged_video_path": self.merged_video_path,
        }
