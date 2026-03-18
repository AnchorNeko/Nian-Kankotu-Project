from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict, Sequence

import requests

from nian_kantoku.application.exceptions import PipelineExecutionError
from nian_kantoku.application.run_models import AssetLayout


class LocalAssetStore:
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
        if not file_path.exists():
            raise PipelineExecutionError(f"Input outline file not found: {file_path}")
        return file_path.read_text(encoding="utf-8")

    def write_json(self, *, file_path: Path, payload: Dict) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def write_jsonl(self, *, file_path: Path, payloads: Sequence[Dict]) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("w", encoding="utf-8") as handle:
            for payload in payloads:
                handle.write(json.dumps(payload, ensure_ascii=False))
                handle.write("\n")

    def download_file(self, *, source_url: str, destination: Path, timeout_sec: int) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)

        if source_url.startswith("file://"):
            source = Path(source_url.replace("file://", "", 1))
            if not source.exists():
                raise PipelineExecutionError(f"Local source file not found: {source}")
            shutil.copyfile(source, destination)
            return

        try:
            response = requests.get(source_url, timeout=timeout_sec, stream=True)
            response.raise_for_status()
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if chunk:
                        handle.write(chunk)
        except requests.RequestException as exc:
            raise PipelineExecutionError(
                f"Failed to download asset from {source_url}: {exc}"
            ) from exc
