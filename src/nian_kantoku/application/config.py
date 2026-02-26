from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

import yaml

from nian_kantoku import ARCH_CONTRACT_VERSION
from nian_kantoku.application.exceptions import ConfigError


@dataclass(frozen=True)
class ModelsConfig:
    storyboard_text_model: str
    image_model: str
    video_model: str


@dataclass(frozen=True)
class RenderConfig:
    width: int
    height: int
    fps: int


@dataclass(frozen=True)
class StoryboardConfig:
    max_shot_duration_sec: float
    max_regen_rounds: int


@dataclass(frozen=True)
class GenerationConfig:
    text_max_retries: int
    task_poll_interval_sec: float
    task_max_polls: int
    request_timeout_sec: int


@dataclass(frozen=True)
class StyleConsistencyConfig:
    base_seed: int
    guidance_scale: float
    optimize_prompt: bool
    max_reference_images_per_shot: int
    carryover_prev_keyframes: int
    prompt_lock_preamble: str
    retry_on_image_generation_error: int


@dataclass(frozen=True)
class PathsConfig:
    character_sheet_file: str
    background_sheet_file: str
    character_designs_dir: str
    background_designs_dir: str
    storyboard_file: str
    keyframes_dir: str
    clips_dir: str
    final_video_file: str
    run_manifest_file: str


@dataclass(frozen=True)
class ConsistencyAssetsConfig:
    max_main_characters: int
    max_backgrounds: int
    max_character_refs_per_shot: int
    fail_on_missing_design_assets: bool


@dataclass(frozen=True)
class AppConfig:
    architecture_contract_version: str
    ark_api_key: str
    models: ModelsConfig
    render: RenderConfig
    storyboard: StoryboardConfig
    generation: GenerationConfig
    style_consistency: StyleConsistencyConfig
    consistency_assets: ConsistencyAssetsConfig
    paths: PathsConfig


_REQUIRED_ENV = "ARK_API_KEY"


def _read_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ConfigError(f"Missing required environment variable: {name}")
    return value


def _required_mapping(payload: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"Config key '{key}' must be a mapping")
    return value


def _coerce_bool(value: Any, *, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "on"}:
            return True
        if lowered in {"false", "0", "no", "off"}:
            return False
    raise ConfigError(f"Config key '{key}' must be a boolean")


def load_config(config_path: Path) -> AppConfig:
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}

    if not isinstance(data, dict):
        raise ConfigError("Top-level config must be a mapping")

    architecture_contract_version = str(data.get("architecture_contract_version", "")).strip()
    if not architecture_contract_version:
        raise ConfigError("Missing 'architecture_contract_version' in config")
    if architecture_contract_version != ARCH_CONTRACT_VERSION:
        raise ConfigError(
            "Config architecture contract version mismatch: "
            f"expected {ARCH_CONTRACT_VERSION}, got {architecture_contract_version}"
        )

    models = _required_mapping(data, "models")
    render = _required_mapping(data, "render")
    storyboard = _required_mapping(data, "storyboard")
    generation = _required_mapping(data, "generation")
    style_consistency = _required_mapping(data, "style_consistency")
    consistency_assets = _required_mapping(data, "consistency_assets")
    paths = _required_mapping(data, "paths")

    return AppConfig(
        architecture_contract_version=architecture_contract_version,
        ark_api_key=_read_required_env(_REQUIRED_ENV),
        models=ModelsConfig(
            storyboard_text_model=str(models["storyboard_text_model"]),
            image_model=str(models["image_model"]),
            video_model=str(models["video_model"]),
        ),
        render=RenderConfig(
            width=int(render["width"]),
            height=int(render["height"]),
            fps=int(render["fps"]),
        ),
        storyboard=StoryboardConfig(
            max_shot_duration_sec=float(storyboard["max_shot_duration_sec"]),
            max_regen_rounds=int(storyboard["max_regen_rounds"]),
        ),
        generation=GenerationConfig(
            text_max_retries=int(generation["text_max_retries"]),
            task_poll_interval_sec=float(generation["task_poll_interval_sec"]),
            task_max_polls=int(generation["task_max_polls"]),
            request_timeout_sec=int(generation["request_timeout_sec"]),
        ),
        style_consistency=StyleConsistencyConfig(
            base_seed=int(style_consistency["base_seed"]),
            guidance_scale=float(style_consistency["guidance_scale"]),
            optimize_prompt=_coerce_bool(
                style_consistency["optimize_prompt"],
                key="style_consistency.optimize_prompt",
            ),
            max_reference_images_per_shot=int(
                style_consistency["max_reference_images_per_shot"]
            ),
            carryover_prev_keyframes=int(style_consistency["carryover_prev_keyframes"]),
            prompt_lock_preamble=str(style_consistency.get("prompt_lock_preamble", "")),
            retry_on_image_generation_error=int(
                style_consistency["retry_on_image_generation_error"]
            ),
        ),
        consistency_assets=ConsistencyAssetsConfig(
            max_main_characters=int(consistency_assets["max_main_characters"]),
            max_backgrounds=int(consistency_assets["max_backgrounds"]),
            max_character_refs_per_shot=int(
                consistency_assets["max_character_refs_per_shot"]
            ),
            fail_on_missing_design_assets=_coerce_bool(
                consistency_assets["fail_on_missing_design_assets"],
                key="consistency_assets.fail_on_missing_design_assets",
            ),
        ),
        paths=PathsConfig(
            character_sheet_file=str(paths["character_sheet_file"]),
            background_sheet_file=str(paths["background_sheet_file"]),
            character_designs_dir=str(paths["character_designs_dir"]),
            background_designs_dir=str(paths["background_designs_dir"]),
            storyboard_file=str(paths["storyboard_file"]),
            keyframes_dir=str(paths["keyframes_dir"]),
            clips_dir=str(paths["clips_dir"]),
            final_video_file=str(paths["final_video_file"]),
            run_manifest_file=str(paths["run_manifest_file"]),
        ),
    )
