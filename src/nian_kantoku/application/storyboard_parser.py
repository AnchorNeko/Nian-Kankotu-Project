from __future__ import annotations

import json
import re
from typing import Iterable, List, Sequence

from nian_kantoku.application.exceptions import StoryboardParseError
from nian_kantoku.domain.models import (
    OffendingShot,
    Shot,
    Storyboard,
    StoryboardValidationResult,
)


def _extract_json_text(raw_text: str) -> str:
    raw_text = raw_text.strip()
    if not raw_text:
        raise StoryboardParseError("Empty model output")

    code_fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw_text, re.DOTALL)
    if code_fence_match:
        return code_fence_match.group(1)

    if raw_text.startswith("{") and raw_text.endswith("}"):
        return raw_text

    first = raw_text.find("{")
    last = raw_text.rfind("}")
    if first == -1 or last == -1 or first >= last:
        raise StoryboardParseError("Model output does not contain a valid JSON object")
    return raw_text[first : last + 1]


def parse_storyboard(raw_text: str) -> Storyboard:
    json_text = _extract_json_text(raw_text)
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise StoryboardParseError(f"Invalid storyboard JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise StoryboardParseError("Storyboard payload must be a JSON object")

    storyboard = Storyboard.from_dict(payload)
    _assert_unique_shot_ids(storyboard.shots)
    _assert_unique_background_ids(storyboard)
    _assert_background_references(storyboard)
    return storyboard


def _assert_unique_shot_ids(shots: Iterable[Shot]) -> None:
    seen = set()
    for shot in shots:
        if shot.shot_id in seen:
            raise StoryboardParseError(f"Duplicate shot_id found: {shot.shot_id}")
        seen.add(shot.shot_id)


def _assert_unique_background_ids(storyboard: Storyboard) -> None:
    seen = set()
    for background in storyboard.backgrounds:
        if background.background_id in seen:
            raise StoryboardParseError(
                f"Duplicate background_id found: {background.background_id}"
            )
        seen.add(background.background_id)


def _assert_background_references(storyboard: Storyboard) -> None:
    background_ids = {item.background_id for item in storyboard.backgrounds}
    for shot in storyboard.shots:
        if shot.background_id not in background_ids:
            raise StoryboardParseError(
                f"Shot {shot.shot_id} references missing background_id={shot.background_id}"
            )


def validate_storyboard_references(
    *,
    storyboard: Storyboard,
    allowed_character_ids: Sequence[str],
) -> None:
    allowed = {item for item in allowed_character_ids if item}
    if not allowed:
        raise StoryboardParseError("No allowed character IDs provided for storyboard validation")

    for shot in storyboard.shots:
        if not shot.character_ids:
            raise StoryboardParseError(f"Shot {shot.shot_id} must include character_ids")
        missing = [char_id for char_id in shot.character_ids if char_id not in allowed]
        if missing:
            raise StoryboardParseError(
                f"Shot {shot.shot_id} references unknown character_ids={sorted(set(missing))}"
            )


def validate_storyboard(
    storyboard: Storyboard,
    *,
    max_shot_duration_sec: float,
    regen_round: int,
) -> StoryboardValidationResult:
    offending_shots: List[OffendingShot] = []
    valid_shots: List[Shot] = []

    for shot in storyboard.shots:
        if shot.duration_sec > max_shot_duration_sec:
            offending_shots.append(
                OffendingShot(
                    shot_id=shot.shot_id,
                    duration_sec=shot.duration_sec,
                )
            )
        else:
            valid_shots.append(shot)

    return StoryboardValidationResult(
        valid_shots=valid_shots,
        offending_shots=offending_shots,
        regen_round=regen_round,
    )


def merge_storyboard_with_regenerated_shots(
    *,
    current_storyboard: Storyboard,
    regenerated_storyboard: Storyboard,
    offending_shot_ids: Iterable[str],
) -> Storyboard:
    offending_id_set = set(offending_shot_ids)
    if not offending_id_set:
        return current_storyboard

    regenerated_map = {shot.shot_id: shot for shot in regenerated_storyboard.shots}
    missing = offending_id_set.difference(regenerated_map.keys())
    if missing:
        raise StoryboardParseError(
            "Regeneration response is missing offending shot IDs: "
            f"{sorted(missing)}"
        )

    merged_shots: List[Shot] = []
    for shot in current_storyboard.shots:
        if shot.shot_id in offending_id_set:
            merged_shots.append(regenerated_map[shot.shot_id])
        else:
            merged_shots.append(shot)

    return Storyboard(
        shots=merged_shots,
        backgrounds=regenerated_storyboard.backgrounds or current_storyboard.backgrounds,
        style_guide=regenerated_storyboard.style_guide or current_storyboard.style_guide,
        total_planned_duration=sum(shot.duration_sec for shot in merged_shots),
    )
