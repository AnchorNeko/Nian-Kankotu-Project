from __future__ import annotations

from nian_kantoku.application.prompt_templates import (
    build_background_design_prompt,
    build_character_extraction_prompt,
    build_effective_image_prompt,
    build_effective_video_prompt,
    build_global_style_lock_text,
    build_shot_continuity_lock_text,
    build_storyboard_prompt,
    build_storyboard_regeneration_prompt,
)
from nian_kantoku.domain.models import BackgroundSpec, CharacterSpec, OffendingShot, Shot, Storyboard


def test_character_extraction_prompt_contains_limit_and_schema() -> None:
    prompt = build_character_extraction_prompt(
        outline="hero rises",
        max_main_characters=4,
    )

    assert "Return at most 4 characters" in prompt
    assert "character_id" in prompt
    assert "design_prompt" in prompt


def test_storyboard_prompt_contains_duration_constraint_and_consistency_schema() -> None:
    prompt = build_storyboard_prompt(
        outline="hero rises",
        max_shot_duration_sec=15,
        character_specs=[
            CharacterSpec(
                character_id="character_001",
                display_name="Hero",
                identity_description="red hair",
                design_prompt="hero sheet",
            )
        ],
        max_backgrounds=6,
    )

    assert "duration_sec <= 15" in prompt
    assert "split it into more shots" in prompt
    assert "character_ids" in prompt
    assert "background_id" in prompt
    assert "backgrounds" in prompt


def test_regeneration_prompt_contains_offending_shots() -> None:
    storyboard = Storyboard(
        shots=[
            Shot(
                shot_id="shot_001",
                duration_sec=20,
                story_beat="a",
                camera_instruction="b",
                image_prompt="c",
                video_prompt="d",
                character_ids=["character_001"],
                background_id="background_001",
            )
        ],
        backgrounds=[
            BackgroundSpec(
                background_id="background_001",
                display_name="street",
                location_description="small street",
                visual_constraints="warm light",
                design_prompt="street sheet",
            )
        ],
        style_guide="anime",
        total_planned_duration=20,
    )

    prompt = build_storyboard_regeneration_prompt(
        outline="outline",
        current_storyboard=storyboard,
        offending_shots=[OffendingShot(shot_id="shot_001", duration_sec=20)],
        max_shot_duration_sec=15,
    )

    assert "shot_001" in prompt
    assert "duration_sec <= 15" in prompt
    assert "background_id" in prompt


def test_effective_image_prompt_contains_consistency_constraints() -> None:
    global_lock = build_global_style_lock_text(
        style_guide="soft anime palette",
        lock_preamble="Strict consistency mode.",
    )
    continuity = build_shot_continuity_lock_text(
        previous_shot_id="shot_001",
        previous_story_beat="hero smiles",
    )
    prompt = build_effective_image_prompt(
        global_style_lock_text=global_lock,
        character_context="- character_001: red hair",
        background_context="- background_001: market street",
        shot_image_prompt="hero in market street",
        continuity_lock_text=continuity,
        anti_drift_constraints="No random outfit swaps.",
    )

    assert "Strict consistency mode." in prompt
    assert "character_001" in prompt
    assert "background_001" in prompt
    assert "No random outfit swaps." in prompt


def test_effective_video_prompt_contains_design_context_and_render_params() -> None:
    prompt = build_effective_video_prompt(
        shot_video_prompt="camera pans left",
        character_context="- character_001: red hair",
        background_context="- background_001: market street",
        shot_duration_sec=5.0,
        render_width=1280,
        render_height=720,
        render_fps=24,
    )

    assert "camera pans left" in prompt
    assert "character_001" in prompt
    assert "background_001" in prompt
    assert "1280x720" in prompt


def test_background_design_prompt_contains_related_characters() -> None:
    prompt = build_background_design_prompt(
        background_spec=BackgroundSpec(
            background_id="background_001",
            display_name="market",
            location_description="busy market",
            visual_constraints="sunset",
            design_prompt="anime market",
        ),
        style_guide="anime style",
        related_characters=[
            CharacterSpec(
                character_id="character_001",
                display_name="Hero",
                identity_description="red hair",
                design_prompt="hero sheet",
            )
        ],
    )

    assert "background_001" in prompt
    assert "character_001" in prompt
    assert "anime market" in prompt
