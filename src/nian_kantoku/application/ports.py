from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Protocol, Sequence

from nian_kantoku.application.run_models import AssetLayout, GeneratedImageReference, VideoTaskStatus


class StoryboardModelPort(Protocol):
    def generate_storyboard(self, *, model: str, prompt: str) -> str:
        ...


class ImageGeneratorPort(Protocol):
    def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        width: int,
        height: int,
        reference_images: Sequence[str],
        seed: int | None,
        guidance_scale: float | None,
        optimize_prompt: bool | None,
    ) -> GeneratedImageReference:
        ...


class VideoGeneratorPort(Protocol):
    def create_video_task(
        self,
        *,
        model: str,
        prompt: str,
        image_url: str,
    ) -> str:
        ...

    def get_video_task_status(self, *, task_id: str) -> VideoTaskStatus:
        ...


class AssetStorePort(Protocol):
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
        ...

    def read_text(self, *, file_path: Path) -> str:
        ...

    def write_json(self, *, file_path: Path, payload: Dict) -> None:
        ...

    def write_jsonl(self, *, file_path: Path, payloads: Sequence[Dict]) -> None:
        ...

    def download_file(self, *, source_url: str, destination: Path, timeout_sec: int) -> None:
        ...


class ClipMergerPort(Protocol):
    def merge_clips(
        self,
        *,
        clip_paths: List[Path],
        output_path: Path,
        width: int,
        height: int,
        fps: int,
    ) -> None:
        ...


class RuntimeDependencyPort(Protocol):
    def ensure_ffmpeg(self) -> None:
        ...
