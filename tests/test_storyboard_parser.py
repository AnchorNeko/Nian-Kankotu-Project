from __future__ import annotations

import json

import pytest

from nian_kantoku.application.storyboard_parser import (
    merge_storyboard_with_regenerated_shots,
    parse_storyboard,
    validate_storyboard,
    validate_storyboard_references,
)
from nian_kantoku.domain.models import BackgroundSpec, Shot, Storyboard


def test_parse_storyboard_from_code_fence() -> None:
    payload = {
        "shots": [
            {
                "shot_id": "shot_001",
                "duration_sec": 6,
                "story_beat": "x",
                "camera_instruction": "y",
                "image_prompt": "z",
                "video_prompt": "v",
                "character_ids": ["character_001"],
                "background_id": "background_001",
            }
        ],
        "backgrounds": [
            {
                "background_id": "background_001",
                "display_name": "street",
                "location_description": "street",
                "visual_constraints": "warm",
                "design_prompt": "street prompt",
            }
        ],
    }
    raw = f"```json\n{json.dumps(payload)}\n```"

    storyboard = parse_storyboard(raw)
    assert storyboard.shots[0].shot_id == "shot_001"


def test_validate_storyboard_detects_offending_shots() -> None:
    storyboard = Storyboard(
        shots=[
            Shot("shot_001", 10, "a", "b", "c", "d", ["character_001"], "background_001"),
            Shot("shot_002", 20, "a", "b", "c", "d", ["character_001"], "background_001"),
        ],
        backgrounds=[
            BackgroundSpec(
                background_id="background_001",
                display_name="street",
                location_description="street",
                visual_constraints="warm",
                design_prompt="street prompt",
            )
        ],
    )

    result = validate_storyboard(
        storyboard,
        max_shot_duration_sec=15,
        regen_round=0,
    )

    assert len(result.offending_shots) == 1
    assert result.offending_shots[0].shot_id == "shot_002"


def test_validate_storyboard_references_requires_known_characters() -> None:
    storyboard = Storyboard(
        shots=[
            Shot(
                "shot_001",
                10,
                "a",
                "b",
                "c",
                "d",
                ["character_999"],
                "background_001",
            )
        ],
        backgrounds=[
            BackgroundSpec(
                background_id="background_001",
                display_name="street",
                location_description="street",
                visual_constraints="warm",
                design_prompt="street prompt",
            )
        ],
    )

    with pytest.raises(Exception):
        validate_storyboard_references(
            storyboard=storyboard,
            allowed_character_ids=["character_001"],
        )


def test_merge_storyboard_with_regenerated_shots() -> None:
    current = Storyboard(
        shots=[
            Shot("shot_001", 20, "a", "b", "c", "d", ["character_001"], "background_001"),
            Shot("shot_002", 8, "a", "b", "c", "d", ["character_001"], "background_001"),
        ],
        backgrounds=[
            BackgroundSpec(
                background_id="background_001",
                display_name="street",
                location_description="street",
                visual_constraints="warm",
                design_prompt="street prompt",
            )
        ],
    )
    regenerated = Storyboard(
        shots=[
            Shot(
                "shot_001",
                12,
                "new",
                "new",
                "new",
                "new",
                ["character_001"],
                "background_001",
            ),
            Shot(
                "shot_002",
                8,
                "changed",
                "changed",
                "changed",
                "changed",
                ["character_001"],
                "background_001",
            ),
        ],
        backgrounds=[
            BackgroundSpec(
                background_id="background_001",
                display_name="street",
                location_description="street",
                visual_constraints="warm",
                design_prompt="street prompt",
            )
        ],
    )

    merged = merge_storyboard_with_regenerated_shots(
        current_storyboard=current,
        regenerated_storyboard=regenerated,
        offending_shot_ids=["shot_001"],
    )

    assert merged.shots[0].duration_sec == 12
    assert merged.shots[1].story_beat == "a"


def test_merge_storyboard_requires_offending_id_presence() -> None:
    current = Storyboard(
        shots=[Shot("shot_001", 20, "a", "b", "c", "d", ["character_001"], "background_001")],
        backgrounds=[
            BackgroundSpec(
                background_id="background_001",
                display_name="street",
                location_description="street",
                visual_constraints="warm",
                design_prompt="street prompt",
            )
        ],
    )
    regenerated = Storyboard(
        shots=[Shot("shot_999", 12, "a", "b", "c", "d", ["character_001"], "background_001")],
        backgrounds=[
            BackgroundSpec(
                background_id="background_001",
                display_name="street",
                location_description="street",
                visual_constraints="warm",
                design_prompt="street prompt",
            )
        ],
    )

    with pytest.raises(Exception):
        merge_storyboard_with_regenerated_shots(
            current_storyboard=current,
            regenerated_storyboard=regenerated,
            offending_shot_ids=["shot_001"],
        )
