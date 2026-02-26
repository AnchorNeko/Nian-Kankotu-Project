from __future__ import annotations

from pathlib import Path

import pytest

from nian_kantoku.application.config import load_config
from nian_kantoku.application.exceptions import ConfigError


@pytest.fixture
def config_path() -> Path:
    return Path("config/settings.yaml")


def test_load_config_success(monkeypatch: pytest.MonkeyPatch, config_path: Path) -> None:
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    config = load_config(config_path)

    assert config.models.storyboard_text_model == "doubao-seed-2-0-pro-260215"
    assert config.storyboard.max_regen_rounds == 3
    assert config.render.fps == 24
    assert config.style_consistency.base_seed == 20260225
    assert config.style_consistency.optimize_prompt is False
    assert config.consistency_assets.max_main_characters == 4
    assert config.consistency_assets.fail_on_missing_design_assets is True
    assert config.paths.character_sheet_file == "character_sheet.json"
    assert config.paths.background_designs_dir == "background_designs"


def test_load_config_missing_api_key(
    monkeypatch: pytest.MonkeyPatch,
    config_path: Path,
) -> None:
    monkeypatch.delenv("ARK_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        load_config(config_path)


def test_load_config_requires_style_consistency_block(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("ARK_API_KEY", "test-key")
    broken_config = tmp_path / "broken.yaml"
    broken_config.write_text(
        """
architecture_contract_version: "1.0.0"
models:
  storyboard_text_model: "a"
  image_model: "b"
  video_model: "c"
render:
  width: 1280
  height: 720
  fps: 24
storyboard:
  max_shot_duration_sec: 15
  max_regen_rounds: 3
generation:
  text_max_retries: 1
  task_poll_interval_sec: 1
  task_max_polls: 10
  request_timeout_sec: 60
paths:
  storyboard_file: "storyboard.json"
  keyframes_dir: "keyframes"
  clips_dir: "clips"
  final_video_file: "final.mp4"
  run_manifest_file: "run_manifest.json"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError):
        load_config(broken_config)
