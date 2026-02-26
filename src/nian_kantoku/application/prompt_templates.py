from __future__ import annotations

import json
from typing import Iterable, Optional

from nian_kantoku.domain.models import BackgroundSpec, CharacterSpec, OffendingShot, Storyboard


def build_character_extraction_prompt(*, outline: str, max_main_characters: int) -> str:
    schema = {
        "characters": [
            {
                "character_id": "character_001",
                "display_name": "Character name",
                "identity_description": "stable identity, appearance, outfit, personality anchors",
                "design_prompt": "prompt used to generate a stable character design sheet image",
            }
        ]
    }
    return (
        "You are a lead anime character designer. "
        "Extract the main recurring characters from the plot outline and return JSON only. "
        f"Return at most {max_main_characters} characters. "
        "Character IDs must be stable snake_case with numeric suffixes, e.g. character_001. "
        "identity_description must include stable visual identity and outfit continuity anchors. "
        "design_prompt must be specific enough to generate a full-body anime character sheet.\n"
        "Use this exact schema and field names:\n"
        f"{json.dumps(schema, ensure_ascii=True, indent=2)}\n\n"
        "Plot outline:\n"
        f"{outline}"
    )


def build_character_design_prompt(*, character_spec: CharacterSpec, style_guide: str) -> str:
    return (
        "Generate one anime character design sheet image.\n"
        "Must preserve identity and outfit continuity across shots.\n"
        f"Character ID: {character_spec.character_id}\n"
        f"Character Name: {character_spec.display_name}\n"
        f"Identity Description: {character_spec.identity_description}\n"
        f"Style Guide: {style_guide or 'Consistent anime production style.'}\n"
        "Design Intent:\n"
        f"{character_spec.design_prompt}\n"
        "Output one coherent character design sheet image only."
    )


def build_storyboard_prompt(
    *,
    outline: str,
    max_shot_duration_sec: float,
    character_specs: Iterable[CharacterSpec],
    max_backgrounds: int,
) -> str:
    character_payload = [item.to_dict() for item in character_specs]
    schema = {
        "shots": [
            {
                "shot_id": "shot_001",
                "duration_sec": 5,
                "story_beat": "what happens in this shot",
                "camera_instruction": "camera language and framing",
                "image_prompt": "prompt for keyframe generation",
                "video_prompt": "prompt for clip generation",
                "character_ids": ["character_001"],
                "background_id": "background_001",
            }
        ],
        "backgrounds": [
            {
                "background_id": "background_001",
                "display_name": "location name",
                "location_description": "stable world/location description",
                "visual_constraints": "lighting, palette, architecture, weather continuity anchors",
                "design_prompt": "prompt used to generate a stable background design image",
            }
        ],
        "style_guide": "anime style guide summary",
        "total_planned_duration": 0,
    }
    return (
        "You are a professional Japanese animation storyboard artist. "
        "Convert the plot outline into a structured storyboard JSON. "
        f"Every shot must have duration_sec <= {max_shot_duration_sec}. "
        "If content is too dense, split it into more shots. "
        "Every shot must explicitly bind to character_ids and one background_id. "
        "Use character IDs from the provided character sheet only. "
        f"Define up to {max_backgrounds} reusable location-level backgrounds in backgrounds[]. "
        "background_id referenced by shots must exist in backgrounds[]. "
        "Return JSON only, no markdown, no explanations. "
        "Use this exact schema and field names:\n"
        f"{json.dumps(schema, ensure_ascii=True, indent=2)}\n\n"
        "Character sheet JSON:\n"
        f"{json.dumps(character_payload, ensure_ascii=True)}\n\n"
        "Plot outline:\n"
        f"{outline}"
    )


def build_storyboard_regeneration_prompt(
    *,
    outline: str,
    current_storyboard: Storyboard,
    offending_shots: Iterable[OffendingShot],
    max_shot_duration_sec: float,
) -> str:
    offending_payload = [shot.to_dict() for shot in offending_shots]
    return (
        "You generated a storyboard where some shots violate duration rules. "
        f"Regenerate only the offending shots so each has duration_sec <= {max_shot_duration_sec}. "
        "Keep shot_id stable for regenerated shots. "
        "Do not remove character_ids or background_id in any shot. "
        "background_id must map to backgrounds[].background_id. "
        "Do not change non-offending shot IDs. "
        "Return a full storyboard JSON with all shots so it can be directly merged. "
        "Return JSON only.\n\n"
        "Plot outline:\n"
        f"{outline}\n\n"
        "Current storyboard JSON:\n"
        f"{json.dumps(current_storyboard.to_dict(), ensure_ascii=True)}\n\n"
        "Offending shots:\n"
        f"{json.dumps(offending_payload, ensure_ascii=True)}"
    )


def build_background_design_prompt(
    *,
    background_spec: BackgroundSpec,
    style_guide: str,
    related_characters: Iterable[CharacterSpec],
) -> str:
    related_payload = [
        {
            "character_id": item.character_id,
            "display_name": item.display_name,
            "identity_description": item.identity_description,
        }
        for item in related_characters
    ]
    return (
        "Generate one anime background design sheet image for cross-shot consistency.\n"
        f"Background ID: {background_spec.background_id}\n"
        f"Background Name: {background_spec.display_name}\n"
        f"Location Description: {background_spec.location_description}\n"
        f"Visual Constraints: {background_spec.visual_constraints}\n"
        f"Style Guide: {style_guide or 'Consistent anime production style.'}\n"
        f"Related Characters Context: {json.dumps(related_payload, ensure_ascii=True)}\n"
        "Design Intent:\n"
        f"{background_spec.design_prompt}\n"
        "Output one coherent location design sheet image only."
    )


def build_global_style_lock_text(*, style_guide: str, lock_preamble: str = "") -> str:
    sections = [
        lock_preamble.strip(),
        "Global style lock (must preserve across all shots):",
        style_guide.strip() or "Keep stable anime visual style with consistent lineart and palette.",
        "Identity lock rules:",
        "- Preserve character identity, face shape, hairstyle, hair color, and signature traits.",
        "- Preserve outfit continuity unless explicitly changed by the shot.",
        "- Preserve background world style and lighting logic.",
        "- Do not replace or introduce main characters without explicit instruction.",
    ]
    return "\n".join(item for item in sections if item)


def build_shot_continuity_lock_text(
    *,
    previous_shot_id: Optional[str],
    previous_story_beat: Optional[str],
) -> str:
    if not previous_shot_id:
        return "Continuity lock: keep baseline character and world consistency from reference images."
    prev_story_text = previous_story_beat or "previous shot"
    return (
        "Continuity lock:\n"
        f"- Maintain continuity with previous successful shot {previous_shot_id}.\n"
        f"- Preserve appearance continuity from context: {prev_story_text}.\n"
        "- Keep facial proportions, clothing identity, and background rendering style stable."
    )


def build_anti_drift_constraints() -> str:
    return (
        "Anti-drift constraints:\n"
        "- No random hairstyle/color swaps.\n"
        "- No random outfit swaps.\n"
        "- No random character replacement.\n"
        "- Keep consistent line weight, shading style, and color script."
    )


def build_effective_image_prompt(
    *,
    global_style_lock_text: str,
    character_context: str,
    background_context: str,
    shot_image_prompt: str,
    continuity_lock_text: str,
    anti_drift_constraints: str,
) -> str:
    return (
        f"{global_style_lock_text}\n\n"
        "Character design sheet context:\n"
        f"{character_context}\n\n"
        "Background design sheet context:\n"
        f"{background_context}\n\n"
        "Shot-specific image intent:\n"
        f"{shot_image_prompt}\n\n"
        f"{continuity_lock_text}\n\n"
        f"{anti_drift_constraints}\n\n"
        "Output one coherent anime keyframe image only."
    )


def build_effective_video_prompt(
    *,
    shot_video_prompt: str,
    character_context: str,
    background_context: str,
    shot_duration_sec: float,
    render_width: int,
    render_height: int,
    render_fps: int,
) -> str:
    return (
        "Storyboard shot intent:\n"
        f"{shot_video_prompt}\n\n"
        "Character consistency context:\n"
        f"{character_context}\n\n"
        "Background consistency context:\n"
        f"{background_context}\n\n"
        f"Soft target duration: {shot_duration_sec:.2f} seconds. "
        f"Target render: {render_width}x{render_height} at {render_fps}fps."
    )
