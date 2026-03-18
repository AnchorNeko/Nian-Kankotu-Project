from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

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
from nian_kantoku.application.exceptions import PipelineExecutionError
from nian_kantoku.application.run_models import AssetLayout, GeneratedImageReference, VideoTaskStatus
from nian_kantoku.application.use_cases import (
    GenerateAnimeVideoRequest,
    GenerateAnimeVideoUseCase,
)


class FakeStoryboardModel:
    def __init__(self):
        self.call_count = 0

    def generate_storyboard(self, *, model: str, prompt: str) -> str:
        del model
        self.call_count += 1

        if self.call_count == 1:
            return json.dumps(
                {
                    "characters": [
                        {
                            "character_id": "character_001",
                            "display_name": "Yuko",
                            "identity_description": "pink hair and horns",
                            "design_prompt": "full body character sheet for yuko",
                        },
                        {
                            "character_id": "character_002",
                            "display_name": "Momo",
                            "identity_description": "navy hair cool expression",
                            "design_prompt": "full body character sheet for momo",
                        },
                    ]
                }
            )

        if self.call_count == 2:
            return json.dumps(
                {
                    "shots": [
                        {
                            "shot_id": "shot_001",
                            "duration_sec": 18,
                            "story_beat": "intro",
                            "camera_instruction": "wide",
                            "image_prompt": "img1",
                            "video_prompt": "vid1",
                            "character_ids": ["character_001", "character_002"],
                            "background_id": "background_001",
                        },
                        {
                            "shot_id": "shot_002",
                            "duration_sec": 8,
                            "story_beat": "reaction",
                            "camera_instruction": "close",
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
                            "design_prompt": "anime shopping street layout",
                        }
                    ],
                    "style_guide": "anime",
                    "total_planned_duration": 26,
                }
            )

        assert "Offending shots" in prompt
        return json.dumps(
            {
                "shots": [
                    {
                        "shot_id": "shot_001",
                        "duration_sec": 12,
                        "story_beat": "intro refined",
                        "camera_instruction": "wide refined",
                        "image_prompt": "img1 refined",
                        "video_prompt": "vid1 refined",
                        "character_ids": ["character_001", "character_002"],
                        "background_id": "background_001",
                    },
                    {
                        "shot_id": "shot_002",
                        "duration_sec": 8,
                        "story_beat": "reaction",
                        "camera_instruction": "close",
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
                        "design_prompt": "anime shopping street layout",
                    }
                ],
                "style_guide": "anime",
                "total_planned_duration": 20,
            }
        )


class FakeImageGenerator:
    def __init__(self, image_path: Path):
        self.image_path = image_path
        self.prompts: list[str] = []

    def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        width: int,
        height: int,
        reference_images: list[str],
        seed: int | None,
        guidance_scale: float | None,
        optimize_prompt: bool | None,
    ) -> GeneratedImageReference:
        del model, width, height, reference_images, seed, guidance_scale, optimize_prompt
        self.prompts.append(prompt)
        return GeneratedImageReference(image_url=f"file://{self.image_path}")


class FailingCharacterDesignImageGenerator(FakeImageGenerator):
    def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        width: int,
        height: int,
        reference_images: list[str],
        seed: int | None,
        guidance_scale: float | None,
        optimize_prompt: bool | None,
    ) -> GeneratedImageReference:
        del model, width, height, reference_images, seed, guidance_scale, optimize_prompt
        if "Character ID: character_001" in prompt:
            raise RuntimeError("simulated character design failure")
        return GeneratedImageReference(image_url=f"file://{self.image_path}")


class FakeVideoGenerator:
    def __init__(self, clip_paths: list[Path]):
        self.clip_paths = clip_paths
        self._next = 0
        self._tasks: dict[str, int] = {}

    def create_video_task(
        self,
        *,
        model: str,
        prompt: str,
        image_url: str,
    ) -> str:
        del model, prompt, image_url
        task_id = f"task_{self._next}"
        self._tasks[task_id] = self._next
        self._next += 1
        return task_id

    def get_video_task_status(self, *, task_id: str) -> VideoTaskStatus:
        index = self._tasks[task_id]
        clip_path = self.clip_paths[index]
        return VideoTaskStatus(
            task_id=task_id,
            status="succeeded",
            video_url=f"file://{clip_path}",
            actual_duration_sec=22.0,
        )


class PartialFailVideoGenerator(FakeVideoGenerator):
    def get_video_task_status(self, *, task_id: str) -> VideoTaskStatus:
        index = self._tasks[task_id]
        if index == 1:
            return VideoTaskStatus(
                task_id=task_id,
                status="failed",
                error_message="simulated failure",
            )
        clip_path = self.clip_paths[index]
        return VideoTaskStatus(
            task_id=task_id,
            status="succeeded",
            video_url=f"file://{clip_path}",
            actual_duration_sec=22.0,
        )


class FakeAssetStore:
    def prepare_layout(
        self,
        *,
        output_dir: Path,
        character_sheet_file_name: str,
        background_sheet_file_name: str,
        character_designs_dir_name: str,
        background_designs_dir_name: str,
        storyboard_file_name: str,
        shot_diagnostics_file_name: str,
        keyframes_dir_name: str,
        clips_dir_name: str,
        final_video_file_name: str,
        run_manifest_file_name: str,
    ) -> AssetLayout:
        output_dir.mkdir(parents=True, exist_ok=True)
        character_designs_dir = output_dir / character_designs_dir_name
        background_designs_dir = output_dir / background_designs_dir_name
        keyframes_dir = output_dir / keyframes_dir_name
        clips_dir = output_dir / clips_dir_name
        character_designs_dir.mkdir(parents=True, exist_ok=True)
        background_designs_dir.mkdir(parents=True, exist_ok=True)
        keyframes_dir.mkdir(parents=True, exist_ok=True)
        clips_dir.mkdir(parents=True, exist_ok=True)
        return AssetLayout(
            output_dir=output_dir,
            keyframes_dir=keyframes_dir,
            clips_dir=clips_dir,
            character_designs_dir=character_designs_dir,
            background_designs_dir=background_designs_dir,
            character_sheet_file=output_dir / character_sheet_file_name,
            background_sheet_file=output_dir / background_sheet_file_name,
            storyboard_file=output_dir / storyboard_file_name,
            shot_diagnostics_file=output_dir / shot_diagnostics_file_name,
            final_video_file=output_dir / final_video_file_name,
            manifest_file=output_dir / run_manifest_file_name,
        )

    def read_text(self, *, file_path: Path) -> str:
        return file_path.read_text(encoding="utf-8")

    def write_json(self, *, file_path: Path, payload: dict) -> None:
        file_path.write_text(json.dumps(payload), encoding="utf-8")

    def write_jsonl(self, *, file_path: Path, payloads: list[dict]) -> None:
        lines = [json.dumps(item) for item in payloads]
        file_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    def download_file(self, *, source_url: str, destination: Path, timeout_sec: int) -> None:
        del timeout_sec
        source = Path(source_url.replace("file://", "", 1))
        shutil.copyfile(source, destination)


class FakeClipMerger:
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


class FakeRuntimeDependency:
    def ensure_ffmpeg(self) -> None:
        return


def _build_config() -> AppConfig:
    return AppConfig(
        architecture_contract_version="2.0.0",
        ark_api_key="dummy",
        models=ModelsConfig(
            storyboard_text_model="text-model",
            image_model="image-model",
            video_model="video-model",
        ),
        render=RenderConfig(width=1280, height=720, fps=24),
        storyboard=StoryboardConfig(max_shot_duration_sec=15, max_regen_rounds=3),
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
            shot_diagnostics_file="shot_diagnostics.jsonl",
            keyframes_dir="keyframes",
            clips_dir="clips",
            final_video_file="final.mp4",
            run_manifest_file="run_manifest.json",
        ),
    )


def test_use_case_regenerates_overlong_shots_and_completes(tmp_path: Path) -> None:
    outline_file = tmp_path / "outline.txt"
    outline_file.write_text("story outline", encoding="utf-8")

    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"img")
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    clip1.write_bytes(b"clip1")
    clip2.write_bytes(b"clip2")

    output_dir = tmp_path / "output"
    use_case = GenerateAnimeVideoUseCase(
        config=_build_config(),
        storyboard_model=FakeStoryboardModel(),
        image_generator=FakeImageGenerator(image_file),
        video_generator=FakeVideoGenerator([clip1, clip2]),
        asset_store=FakeAssetStore(),
        clip_merger=FakeClipMerger(),
        runtime_dependency=FakeRuntimeDependency(),
    )

    manifest = use_case.execute(
        GenerateAnimeVideoRequest(outline_file=outline_file, output_dir=output_dir)
    )

    assert manifest.storyboard_regen_rounds == 1
    assert manifest.run_status == "succeeded"
    assert manifest.total_shots == 2
    assert manifest.succeeded_shots == 2
    assert manifest.failed_shots == 0
    assert manifest.failed_shot_ids == []
    assert manifest.character_design_summary.total == 2
    assert manifest.background_design_summary.total == 1
    assert manifest.merged_video_path == str(output_dir / "final.mp4")
    assert (output_dir / "character_sheet.json").exists()
    assert (output_dir / "background_sheet.json").exists()
    assert (output_dir / "character_designs" / "character_001.png").exists()
    assert (output_dir / "background_designs" / "background_001.png").exists()
    assert (output_dir / "shot_diagnostics.jsonl").exists()
    assert not (output_dir / "style_anchor_manifest.json").exists()

    diagnostics_lines = (output_dir / "shot_diagnostics.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(diagnostics_lines) == 2
    first = json.loads(diagnostics_lines[0])
    assert first["status"] == "succeeded"
    assert first["effective_image_prompt"]
    assert first["effective_video_prompt"]


def test_use_case_continues_after_shot_failure_and_skips_merge(tmp_path: Path) -> None:
    outline_file = tmp_path / "outline.txt"
    outline_file.write_text("story outline", encoding="utf-8")

    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"img")
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    clip1.write_bytes(b"clip1")
    clip2.write_bytes(b"clip2")

    output_dir = tmp_path / "output"
    use_case = GenerateAnimeVideoUseCase(
        config=_build_config(),
        storyboard_model=FakeStoryboardModel(),
        image_generator=FakeImageGenerator(image_file),
        video_generator=PartialFailVideoGenerator([clip1, clip2]),
        asset_store=FakeAssetStore(),
        clip_merger=FakeClipMerger(),
        runtime_dependency=FakeRuntimeDependency(),
    )

    manifest = use_case.execute(
        GenerateAnimeVideoRequest(outline_file=outline_file, output_dir=output_dir)
    )

    assert manifest.run_status == "partial_failed"
    assert manifest.total_shots == 2
    assert manifest.succeeded_shots == 1
    assert manifest.failed_shots == 1
    assert manifest.failed_shot_ids == ["shot_002"]
    assert manifest.merged_video_path == ""
    assert not (output_dir / "final.mp4").exists()
    assert (output_dir / "run_manifest.json").exists()
    assert (output_dir / "shot_diagnostics.jsonl").exists()

    diagnostics_lines = (output_dir / "shot_diagnostics.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(diagnostics_lines) == 2
    second = json.loads(diagnostics_lines[1])
    assert second["status"] == "failed"
    assert second["failed_stage"] == "video_task_poll"
    assert second["character_ids"] == ["character_001"]
    assert second["background_id"] == "background_001"


def test_use_case_fails_fast_when_required_character_design_missing(tmp_path: Path) -> None:
    outline_file = tmp_path / "outline.txt"
    outline_file.write_text("story outline", encoding="utf-8")

    image_file = tmp_path / "image.png"
    image_file.write_bytes(b"img")
    clip1 = tmp_path / "clip1.mp4"
    clip2 = tmp_path / "clip2.mp4"
    clip1.write_bytes(b"clip1")
    clip2.write_bytes(b"clip2")

    use_case = GenerateAnimeVideoUseCase(
        config=_build_config(),
        storyboard_model=FakeStoryboardModel(),
        image_generator=FailingCharacterDesignImageGenerator(image_file),
        video_generator=FakeVideoGenerator([clip1, clip2]),
        asset_store=FakeAssetStore(),
        clip_merger=FakeClipMerger(),
        runtime_dependency=FakeRuntimeDependency(),
    )

    with pytest.raises(PipelineExecutionError):
        use_case.execute(
            GenerateAnimeVideoRequest(outline_file=outline_file, output_dir=tmp_path / "output")
        )
