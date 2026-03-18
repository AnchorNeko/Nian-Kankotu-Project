from __future__ import annotations

import logging
from typing import Callable, Iterable, List, Sequence

from nian_kantoku.application.config import AppConfig
from nian_kantoku.application.exceptions import PipelineExecutionError
from nian_kantoku.application.ports import AssetStorePort, ImageGeneratorPort
from nian_kantoku.application.prompt_templates import (
    build_background_design_prompt,
    build_character_design_prompt,
)
from nian_kantoku.application.run_models import AssetLayout, DesignAssetRecord
from nian_kantoku.domain.models import CharacterSpec, Shot, Storyboard


LogEvent = Callable[..., None]


class DesignAssetService:
    def __init__(
        self,
        *,
        config: AppConfig,
        image_generator: ImageGeneratorPort,
        asset_store: AssetStorePort,
        log_event: LogEvent,
    ) -> None:
        self._config = config
        self._image_generator = image_generator
        self._asset_store = asset_store
        self._log_event = log_event

    def generate_character_design_assets(
        self,
        *,
        layout: AssetLayout,
        character_specs: Sequence[CharacterSpec],
    ) -> List[DesignAssetRecord]:
        records: List[DesignAssetRecord] = []
        for index, character_spec in enumerate(character_specs, start=1):
            prompt = build_character_design_prompt(
                character_spec=character_spec,
                style_guide=self._config.style_consistency.prompt_lock_preamble,
            )
            record = DesignAssetRecord(
                asset_id=character_spec.character_id,
                asset_type="character",
                prompt=prompt,
                status="in_progress",
            )
            records.append(record)

            self._log_event(
                event="character_design_started",
                stage="character_design",
                message=f"Generating character design {character_spec.character_id} ({index}/{len(character_specs)})",
                details={
                    "character_id": character_spec.character_id,
                    "character_name": character_spec.display_name,
                    "design_prompt": prompt,
                },
            )
            try:
                image_ref = self._generate_design_image_with_retries(
                    asset_type="character",
                    asset_id=character_spec.character_id,
                    prompt=prompt,
                    stage="character_design",
                )
                destination = layout.character_designs_dir / f"{character_spec.character_id}.png"
                self._asset_store.download_file(
                    source_url=image_ref.image_url,
                    destination=destination,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                record.image_url = image_ref.image_url
                record.local_path = str(destination)
                record.status = "succeeded"
                self._log_event(
                    event="character_design_succeeded",
                    stage="character_design",
                    message=f"Character design generated for {character_spec.character_id}",
                    details={
                        "character_id": character_spec.character_id,
                        "image_url": image_ref.image_url,
                        "local_path": str(destination),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                record.status = "failed"
                record.error_message = str(exc)
                self._log_event(
                    event="character_design_failed",
                    stage="character_design",
                    message=f"Character design generation failed for {character_spec.character_id}",
                    level=logging.ERROR,
                    error=str(exc),
                    details={"character_id": character_spec.character_id},
                )
        return records

    def generate_background_design_assets(
        self,
        *,
        layout: AssetLayout,
        storyboard: Storyboard,
        character_specs: Sequence[CharacterSpec],
    ) -> List[DesignAssetRecord]:
        character_specs_by_id = {item.character_id: item for item in character_specs}
        records: List[DesignAssetRecord] = []
        for index, background_spec in enumerate(storyboard.backgrounds, start=1):
            related_character_ids = self._collect_related_character_ids(
                storyboard_shots=storyboard.shots,
                background_id=background_spec.background_id,
            )
            related_characters = [
                character_specs_by_id[item]
                for item in related_character_ids
                if item in character_specs_by_id
            ]
            prompt = build_background_design_prompt(
                background_spec=background_spec,
                style_guide=storyboard.style_guide,
                related_characters=related_characters,
            )
            record = DesignAssetRecord(
                asset_id=background_spec.background_id,
                asset_type="background",
                prompt=prompt,
                status="in_progress",
            )
            records.append(record)

            self._log_event(
                event="background_design_started",
                stage="background_design",
                message=(
                    f"Generating background design {background_spec.background_id} "
                    f"({index}/{len(storyboard.backgrounds)})"
                ),
                details={
                    "background_id": background_spec.background_id,
                    "background_name": background_spec.display_name,
                    "design_prompt": prompt,
                    "related_character_ids": related_character_ids,
                },
            )
            try:
                image_ref = self._generate_design_image_with_retries(
                    asset_type="background",
                    asset_id=background_spec.background_id,
                    prompt=prompt,
                    stage="background_design",
                )
                destination = layout.background_designs_dir / f"{background_spec.background_id}.png"
                self._asset_store.download_file(
                    source_url=image_ref.image_url,
                    destination=destination,
                    timeout_sec=self._config.generation.request_timeout_sec,
                )
                record.image_url = image_ref.image_url
                record.local_path = str(destination)
                record.status = "succeeded"
                self._log_event(
                    event="background_design_succeeded",
                    stage="background_design",
                    message=f"Background design generated for {background_spec.background_id}",
                    details={
                        "background_id": background_spec.background_id,
                        "image_url": image_ref.image_url,
                        "local_path": str(destination),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                record.status = "failed"
                record.error_message = str(exc)
                self._log_event(
                    event="background_design_failed",
                    stage="background_design",
                    message=f"Background design generation failed for {background_spec.background_id}",
                    level=logging.ERROR,
                    error=str(exc),
                    details={"background_id": background_spec.background_id},
                )
        return records

    def enforce_required_design_assets(
        self,
        *,
        records: Sequence[DesignAssetRecord],
        stage: str,
        asset_type: str,
    ) -> None:
        failed_ids = [item.asset_id for item in records if item.status != "succeeded" or not item.image_url]
        if not failed_ids:
            return

        self._log_event(
            event=f"{asset_type}_design_assets_incomplete",
            stage=stage,
            message=f"{asset_type.capitalize()} design assets incomplete: {failed_ids}",
            level=logging.WARNING,
            details={"failed_asset_ids": failed_ids},
        )
        if self._config.consistency_assets.fail_on_missing_design_assets:
            raise PipelineExecutionError(
                f"Required {asset_type} design assets are missing: {failed_ids}"
            )

    def _generate_design_image_with_retries(
        self,
        *,
        asset_type: str,
        asset_id: str,
        prompt: str,
        stage: str,
    ):
        attempts = 1 + max(0, self._config.style_consistency.retry_on_image_generation_error)
        last_error: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                if attempt > 1:
                    self._log_event(
                        event=f"{asset_type}_design_retry",
                        stage=stage,
                        message=(
                            f"Retry {asset_type} design image generation for {asset_id}, "
                            f"attempt {attempt}/{attempts}"
                        ),
                        level=logging.WARNING,
                    )
                return self._image_generator.generate_image(
                    model=self._config.models.image_model,
                    prompt=prompt,
                    width=self._config.render.width,
                    height=self._config.render.height,
                    reference_images=[],
                    seed=None,
                    guidance_scale=self._config.style_consistency.guidance_scale,
                    optimize_prompt=self._config.style_consistency.optimize_prompt,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc

        raise PipelineExecutionError(
            f"{asset_type.capitalize()} design image generation failed after {attempts} "
            f"attempts for asset_id={asset_id}"
        ) from last_error

    @staticmethod
    def _collect_related_character_ids(
        *,
        storyboard_shots: Iterable[Shot],
        background_id: str,
    ) -> List[str]:
        seen: set[str] = set()
        ordered: List[str] = []
        for shot in storyboard_shots:
            if shot.background_id != background_id:
                continue
            for char_id in shot.character_ids:
                if char_id in seen:
                    continue
                seen.add(char_id)
                ordered.append(char_id)
        return ordered
