from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import List

from nian_kantoku.application.exceptions import PipelineExecutionError


class FfmpegClipMerger:
    def merge_clips(
        self,
        *,
        clip_paths: List[Path],
        output_path: Path,
        width: int,
        height: int,
        fps: int,
    ) -> None:
        if not clip_paths:
            raise PipelineExecutionError("No clips available for merging")

        for clip_path in clip_paths:
            if not clip_path.exists():
                raise PipelineExecutionError(f"Clip not found: {clip_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as temp_file:
            concat_file = Path(temp_file.name)
            for clip_path in clip_paths:
                escaped = str(clip_path).replace("'", "'\\''")
                temp_file.write(f"file '{escaped}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-vf",
            f"scale={width}:{height}",
            "-r",
            str(fps),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        concat_file.unlink(missing_ok=True)

        if result.returncode != 0:
            raise PipelineExecutionError(
                "ffmpeg merge failed with non-zero exit code. "
                f"stderr: {result.stderr.strip()}"
            )
