from __future__ import annotations

import logging
from typing import Callable, List, Sequence, Tuple

from nian_kantoku.application.config import AppConfig
from nian_kantoku.application.exceptions import PipelineExecutionError, StoryboardRegenerationError
from nian_kantoku.application.json_utils import parse_json_object
from nian_kantoku.application.ports import StoryboardModelPort
from nian_kantoku.application.prompt_templates import (
    build_character_extraction_prompt,
    build_storyboard_prompt,
    build_storyboard_regeneration_prompt,
)
from nian_kantoku.application.storyboard_parser import (
    merge_storyboard_with_regenerated_shots,
    parse_storyboard,
    validate_storyboard,
    validate_storyboard_references,
)
from nian_kantoku.domain.models import CharacterSpec, Storyboard


LogEvent = Callable[..., None]


class StoryboardService:
    def __init__(
        self,
        *,
        config: AppConfig,
        storyboard_model: StoryboardModelPort,
        log_event: LogEvent,
    ) -> None:
        self._config = config
        self._storyboard_model = storyboard_model
        self._log_event = log_event

    def extract_main_characters(self, *, outline: str) -> List[CharacterSpec]:
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

    def generate_storyboard_with_regeneration(
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
                )
                payload = parse_json_object(raw_output)
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
    def _assert_unique_character_ids(characters: Sequence[CharacterSpec]) -> None:
        seen: set[str] = set()
        for item in characters:
            character_id = item.character_id.strip()
            if not character_id:
                raise PipelineExecutionError("character_id cannot be empty")
            if character_id in seen:
                raise PipelineExecutionError(f"Duplicate character_id found: {character_id}")
            seen.add(character_id)
