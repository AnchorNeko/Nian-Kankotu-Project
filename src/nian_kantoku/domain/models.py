from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


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
