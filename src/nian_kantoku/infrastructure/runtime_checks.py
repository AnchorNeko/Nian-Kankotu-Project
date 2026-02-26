from __future__ import annotations

import shutil

from nian_kantoku.application.exceptions import MissingDependencyError


class RuntimeDependencyChecker:
    def ensure_ffmpeg(self) -> None:
        if shutil.which("ffmpeg") is None:
            raise MissingDependencyError(
                "ffmpeg is required but was not found in PATH. "
                "Install ffmpeg before running this pipeline."
            )
