from __future__ import annotations

import json
from pathlib import Path

from nian_kantoku.application.config import (
    AppConfig,
    ConsistencyAssetsConfig,
    GenerationConfig,
    ModelsConfig,
    PathsConfig,
    RenderConfig,
    StyleConsistencyConfig,
    StoryboardConfig,
)
from nian_kantoku.domain.models import GeneratedImageReference, VideoTaskStatus
from nian_kantoku.interface import cli as cli_module


def _build_config() -> AppConfig:
    return AppConfig(
        architecture_contract_version="1.0.0",
        ark_api_key="dummy",
        models=ModelsConfig(
            storyboard_text_model="text-model",
            image_model="image-model",
            video_model="video-model",
        ),
        render=RenderConfig(width=1280, height=720, fps=24),
        storyboard=StoryboardConfig(max_shot_duration_sec=15, max_regen_rounds=0),
        generation=GenerationConfig(
            text_max_retries=0,
            task_poll_interval_sec=0,
            task_max_polls=1,
            request_timeout_sec=5,
        ),
        style_consistency=StyleConsistencyConfig(
            base_seed=1000,
            guidance_scale=4.5,
            optimize_prompt=False,
            max_reference_images_per_shot=6,
            carryover_prev_keyframes=2,
            prompt_lock_preamble="Strict lock",
            retry_on_image_generation_error=1,
        ),
        consistency_assets=ConsistencyAssetsConfig(
            max_main_characters=4,
            max_backgrounds=6,
            max_character_refs_per_shot=2,
            fail_on_missing_design_assets=True,
        ),
        paths=PathsConfig(
            character_sheet_file="character_sheet.json",
            background_sheet_file="background_sheet.json",
            character_designs_dir="character_designs",
            background_designs_dir="background_designs",
            storyboard_file="storyboard.json",
            keyframes_dir="keyframes",
            clips_dir="clips",
            final_video_file="final.mp4",
            run_manifest_file="run_manifest.json",
        ),
    )


class _FakeStoryboardModel:
    def __init__(self) -> None:
        self.call_count = 0

    def generate_storyboard(self, *, model: str, prompt: str, timeout_sec: int) -> str:
        del model, timeout_sec, prompt
        self.call_count += 1
        if self.call_count == 1:
            return json.dumps(
                {
                    "characters": [
                        {
                            "character_id": "character_001",
                            "display_name": "Yuko",
                            "identity_description": "pink hair and horns",
                            "design_prompt": "full body character sheet",
                        }
                    ]
                }
            )
        return json.dumps(
            {
                "shots": [
                    {
                        "shot_id": "shot_001",
                        "duration_sec": 5,
                        "story_beat": "a",
                        "camera_instruction": "b",
                        "image_prompt": "img1",
                        "video_prompt": "vid1",
                        "character_ids": ["character_001"],
                        "background_id": "background_001",
                    },
                    {
                        "shot_id": "shot_002",
                        "duration_sec": 5,
                        "story_beat": "c",
                        "camera_instruction": "d",
                        "image_prompt": "img2",
                        "video_prompt": "vid2",
                        "character_ids": ["character_001"],
                        "background_id": "background_001",
                    },
                ],
                "backgrounds": [
                    {
                        "background_id": "background_001",
                        "display_name": "street",
                        "location_description": "shopping street",
                        "visual_constraints": "warm afternoon",
                        "design_prompt": "anime shopping street",
                    }
                ],
            }
        )


class _FakeImageGenerator:
    def __init__(self, image_path: Path) -> None:
        self._image_path = image_path
        self.calls = []

    def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        width: int,
        height: int,
        timeout_sec: int,
        reference_images: list[str],
        seed: int | None,
        guidance_scale: float | None,
        optimize_prompt: bool | None,
    ) -> GeneratedImageReference:
        self.calls.append(
            {
                "model": model,
                "prompt": prompt,
                "width": width,
                "height": height,
                "timeout_sec": timeout_sec,
                "reference_images": reference_images,
                "seed": seed,
                "guidance_scale": guidance_scale,
                "optimize_prompt": optimize_prompt,
            }
        )
        return GeneratedImageReference(image_url=f"file://{self._image_path}")


class _PartialFailVideoGenerator:
    def __init__(self, clip_paths: list[Path]) -> None:
        self._clip_paths = clip_paths
        self._next = 0
        self._tasks: dict[str, int] = {}

    def create_video_task(
        self,
        *,
        model: str,
        prompt: str,
        image_url: str,
        duration_sec: float,
        width: int,
        height: int,
        fps: int,
        timeout_sec: int,
    ) -> str:
        del model, prompt, image_url, duration_sec, width, height, fps, timeout_sec
        task_id = f"task_{self._next}"
        self._tasks[task_id] = self._next
        self._next += 1
        return task_id

    def get_video_task_status(self, *, task_id: str, timeout_sec: int) -> VideoTaskStatus:
        del timeout_sec
        index = self._tasks[task_id]
        if index == 1:
            return VideoTaskStatus(
                task_id=task_id,
                status="failed",
                error_message="simulated failure",
            )
        return VideoTaskStatus(
            task_id=task_id,
            status="succeeded",
            video_url=f"file://{self._clip_paths[index]}",
            actual_duration_sec=5.0,
        )


class _FakeClipMerger:
    def merge_clips(
        self,
        *,
        clip_paths: list[Path],
        output_path: Path,
        width: int,
        height: int,
        fps: int,
    ) -> None:
        del width, height, fps
        output_path.write_bytes(b"".join(path.read_bytes() for path in clip_paths))


class _FakeRuntimeDependency:
    def ensure_ffmpeg(self) -> None:
        return


def test_cli_partial_failure_exit_and_log_artifacts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    outline_file = tmp_path / "outline.txt"
    outline_file.write_text("story outline", encoding="utf-8")

    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"image")
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    clip1.write_bytes(b"clip1")
    clip2.write_bytes(b"clip2")

    output_dir = tmp_path / "output"
    config = _build_config()
    video_generator = _PartialFailVideoGenerator([clip1, clip2])
    image_generator = _FakeImageGenerator(image_file)

    monkeypatch.setattr(cli_module, "load_config", lambda _: config)
    monkeypatch.setattr(cli_module, "ArkStoryboardModelAdapter", lambda **_: _FakeStoryboardModel())
    monkeypatch.setattr(cli_module, "ArkImageGeneratorAdapter", lambda **_: image_generator)
    monkeypatch.setattr(cli_module, "ArkVideoGeneratorAdapter", lambda **_: video_generator)
    monkeypatch.setattr(cli_module, "FfmpegClipMerger", lambda: _FakeClipMerger())
    monkeypatch.setattr(cli_module, "RuntimeDependencyChecker", lambda: _FakeRuntimeDependency())

    exit_code = cli_module.main(
        [
            "run",
            "--outline-file",
            str(outline_file),
            "--output-dir",
            str(output_dir),
            "--config",
            str(tmp_path / "config.yaml"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "[Nian-Kantoku Partial Failure]" in captured.err
    assert "partial_failed" in captured.out
    assert "Character consistency context" in captured.out
    assert "Background ID" in captured.out
    assert "storyboard_model_attempt_failed" not in captured.out
    assert "storyboard_model_attempt_failed" not in captured.err
    assert (output_dir / "run_manifest.json").exists()
    assert (output_dir / "run.log").exists()
    assert (output_dir / "events.jsonl").exists()
    assert not (output_dir / "final.mp4").exists()

    event_lines = (output_dir / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert event_lines
    event_payloads = [json.loads(line) for line in event_lines]
    assert any(item.get("event") == "shot_failed" for item in event_payloads)

    required_keys = {
        "timestamp",
        "level",
        "event",
        "stage",
        "message",
        "shot_id",
        "shot_index",
        "total_shots",
        "completed_shots",
        "failed_shots",
        "error",
    }
    assert required_keys.issubset(event_payloads[-1].keys())
    shot_started_events = [item for item in event_payloads if item.get("event") == "shot_started"]
    assert shot_started_events
    first_details = shot_started_events[0].get("details")
    assert isinstance(first_details, dict)
    assert first_details.get("effective_image_prompt")
    assert first_details.get("effective_video_prompt")
    assert first_details.get("character_ids") == ["character_001"]

    run_log_text = (output_dir / "run.log").read_text(encoding="utf-8")
    assert "shot_failed" in run_log_text
    assert "effective_video_prompt" in run_log_text

    run_manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert run_manifest["shot_diagnostics"]
    assert run_manifest["shot_diagnostics"][0]["effective_image_prompt"]
    assert run_manifest["shot_diagnostics"][0]["effective_video_prompt"]
    assert run_manifest["shot_diagnostics"][0]["character_ids"] == ["character_001"]


def test_cli_reference_dir_builds_data_uri_and_passes_into_image_generation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    outline_file = tmp_path / "outline.txt"
    outline_file.write_text("story outline", encoding="utf-8")

    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"image")
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    clip1.write_bytes(b"clip1")
    clip2.write_bytes(b"clip2")

    reference_dir = tmp_path / "references"
    reference_dir.mkdir(parents=True, exist_ok=True)
    (reference_dir / "character_yuko.png").write_bytes(b"char")
    (reference_dir / "style_palette.jpg").write_bytes(b"style")
    (reference_dir / "scene_street.webp").write_bytes(b"scene")

    output_dir = tmp_path / "output"
    config = _build_config()
    video_generator = _PartialFailVideoGenerator([clip1, clip2])
    image_generator = _FakeImageGenerator(image_file)

    monkeypatch.setattr(cli_module, "load_config", lambda _: config)
    monkeypatch.setattr(cli_module, "ArkStoryboardModelAdapter", lambda **_: _FakeStoryboardModel())
    monkeypatch.setattr(cli_module, "ArkImageGeneratorAdapter", lambda **_: image_generator)
    monkeypatch.setattr(cli_module, "ArkVideoGeneratorAdapter", lambda **_: video_generator)
    monkeypatch.setattr(cli_module, "FfmpegClipMerger", lambda: _FakeClipMerger())
    monkeypatch.setattr(cli_module, "RuntimeDependencyChecker", lambda: _FakeRuntimeDependency())

    exit_code = cli_module.main(
        [
            "run",
            "--outline-file",
            str(outline_file),
            "--output-dir",
            str(output_dir),
            "--config",
            str(tmp_path / "config.yaml"),
            "--reference-dir",
            str(reference_dir),
        ]
    )

    assert exit_code == 2
    shot_calls = [item for item in image_generator.calls if item["seed"] is not None]
    assert shot_calls
    first_shot_call = shot_calls[0]
    assert first_shot_call["reference_images"]
    assert first_shot_call["reference_images"][0].startswith(("file://", "data:image/"))
    assert first_shot_call["seed"] == 1001

    style_manifest = json.loads(
        (output_dir / "style_anchor_manifest.json").read_text(encoding="utf-8")
    )
    joined_labels = " ".join(style_manifest["reference_image_inputs"])
    assert "character_yuko.png" in joined_labels
    assert "style_palette.jpg" in joined_labels
    assert "scene_street.webp" in joined_labels


def test_cli_missing_reference_dir_falls_back_without_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    outline_file = tmp_path / "outline.txt"
    outline_file.write_text("story outline", encoding="utf-8")

    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"image")
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    clip1.write_bytes(b"clip1")
    clip2.write_bytes(b"clip2")

    missing_reference_dir = tmp_path / "missing_ref_dir"
    output_dir = tmp_path / "output"
    config = _build_config()
    video_generator = _PartialFailVideoGenerator([clip1, clip2])
    image_generator = _FakeImageGenerator(image_file)

    monkeypatch.setattr(cli_module, "load_config", lambda _: config)
    monkeypatch.setattr(cli_module, "ArkStoryboardModelAdapter", lambda **_: _FakeStoryboardModel())
    monkeypatch.setattr(cli_module, "ArkImageGeneratorAdapter", lambda **_: image_generator)
    monkeypatch.setattr(cli_module, "ArkVideoGeneratorAdapter", lambda **_: video_generator)
    monkeypatch.setattr(cli_module, "FfmpegClipMerger", lambda: _FakeClipMerger())
    monkeypatch.setattr(cli_module, "RuntimeDependencyChecker", lambda: _FakeRuntimeDependency())

    exit_code = cli_module.main(
        [
            "run",
            "--outline-file",
            str(outline_file),
            "--output-dir",
            str(output_dir),
            "--config",
            str(tmp_path / "config.yaml"),
            "--reference-dir",
            str(missing_reference_dir),
        ]
    )

    assert exit_code == 2
    shot_calls = [item for item in image_generator.calls if item["seed"] is not None]
    assert shot_calls
    assert shot_calls[0]["reference_images"]
    # Shot references should still contain generated consistency references even when user dir is missing.
    assert all(not ref.startswith("data:image/") for ref in shot_calls[0]["reference_images"])
    run_log = (output_dir / "run.log").read_text(encoding="utf-8")
    assert "reference_dir_skipped" in run_log
