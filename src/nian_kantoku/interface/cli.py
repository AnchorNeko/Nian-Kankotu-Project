from __future__ import annotations

import argparse
import base64
import logging
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

from nian_kantoku.application.config import load_config
from nian_kantoku.application.exceptions import NianKantokuError
from nian_kantoku.application.use_cases import (
    GenerateAnimeVideoRequest,
    GenerateAnimeVideoUseCase,
)
from nian_kantoku.infrastructure.ark_clients import (
    ArkImageGeneratorAdapter,
    ArkStoryboardModelAdapter,
    ArkVideoGeneratorAdapter,
)
from nian_kantoku.infrastructure.ffmpeg_merger import FfmpegClipMerger
from nian_kantoku.infrastructure.local_store import LocalAssetStore
from nian_kantoku.infrastructure.runtime_checks import RuntimeDependencyChecker
from nian_kantoku.interface.progress_dashboard import RunProgressDashboard
from nian_kantoku.interface.presentation import render_manifest_output
from nian_kantoku.interface.run_logging import configure_run_logging, log_run_event

_ALLOWED_REFERENCE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Nian Kantoku FMVP CLI")
    subparsers = parser.add_subparsers(dest="command")

    run_parser = subparsers.add_parser("run", help="Generate video from plot outline")
    run_parser.add_argument(
        "--outline-file",
        required=True,
        type=Path,
        help="Path to input outline text file",
    )
    run_parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Output directory for generated artifacts",
    )
    run_parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/settings.yaml"),
        help="Path to config yaml (default: config/settings.yaml)",
    )
    run_parser.add_argument(
        "--reference-dir",
        type=Path,
        default=None,
        help=(
            "Optional directory of reference images. "
            "Supports character_*, style_*, scene_* file prefixes."
        ),
    )
    run_parser.add_argument(
        "--output-format",
        choices=("pretty", "json"),
        default="pretty",
        help="User-facing CLI output format (default: pretty)",
    )
    return parser


def _infer_reference_bucket(file_name: str) -> str:
    lowered = file_name.lower()
    if lowered.startswith("character_"):
        return "character"
    if lowered.startswith("style_"):
        return "style"
    if lowered.startswith("scene_"):
        return "scene"
    return "other"


def _to_data_uri(path: Path) -> str:
    mime = _ALLOWED_REFERENCE_EXTENSIONS[path.suffix.lower()]
    content = path.read_bytes()
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _collect_reference_images(
    *,
    reference_dir: Path | None,
    logger: logging.Logger,
) -> Tuple[List[str], List[str]]:
    if reference_dir is None:
        return [], []
    if not reference_dir.exists() or not reference_dir.is_dir():
        log_run_event(
            logger=logger,
            event="reference_dir_skipped",
            stage="style_consistency",
            message=f"Reference directory is missing or invalid, skip: {reference_dir}",
            level=logging.WARNING,
        )
        return [], []

    candidates = [
        item
        for item in sorted(reference_dir.iterdir())
        if item.is_file() and item.suffix.lower() in _ALLOWED_REFERENCE_EXTENSIONS
    ]
    if not candidates:
        log_run_event(
            logger=logger,
            event="reference_dir_empty",
            stage="style_consistency",
            message=f"No valid reference images found in {reference_dir}",
            level=logging.WARNING,
        )
        return [], []

    grouped = {"character": [], "style": [], "scene": [], "other": []}
    for file_path in candidates:
        grouped[_infer_reference_bucket(file_path.name)].append(file_path)

    has_named_bucket = any(grouped[key] for key in ("character", "style", "scene"))
    ordered_files: List[Path]
    forced_bucket: str | None = None
    if has_named_bucket:
        ordered_files = (
            grouped["character"] + grouped["style"] + grouped["scene"] + grouped["other"]
        )
    else:
        ordered_files = candidates
        forced_bucket = "style"

    data_uris: List[str] = []
    labels: List[str] = []
    for file_path in ordered_files:
        try:
            data_uris.append(_to_data_uri(file_path))
            bucket = forced_bucket or _infer_reference_bucket(file_path.name)
            labels.append(f"{bucket}:{file_path.name}")
        except Exception as exc:  # noqa: BLE001
            log_run_event(
                logger=logger,
                event="reference_image_skipped",
                stage="style_consistency",
                message=f"Skip unreadable reference image: {file_path}",
                level=logging.WARNING,
                error=str(exc),
            )

    log_run_event(
        logger=logger,
        event="reference_images_collected",
        stage="style_consistency",
        message=f"Collected {len(data_uris)} reference images from {reference_dir}",
    )
    return data_uris, labels


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command != "run":
        parser.print_help()
        return 1

    logger = configure_run_logging(args.output_dir)
    dashboard = RunProgressDashboard(enabled=args.output_format == "pretty")
    dashboard.start(logger)
    log_run_event(
        logger=logger,
        event="cli_run_invoked",
        stage="cli",
        message=(
            f"Received CLI run command with outline={args.outline_file} "
            f"output_dir={args.output_dir} config={args.config} reference_dir={args.reference_dir}"
        ),
    )

    try:
        config = load_config(args.config)

        storyboard_model = ArkStoryboardModelAdapter(
            api_key=config.ark_api_key,
            request_timeout_sec=config.generation.request_timeout_sec,
        )
        image_generator = ArkImageGeneratorAdapter(
            api_key=config.ark_api_key,
            request_timeout_sec=config.generation.request_timeout_sec,
        )
        video_generator = ArkVideoGeneratorAdapter(
            api_key=config.ark_api_key,
            request_timeout_sec=config.generation.request_timeout_sec,
        )

        use_case = GenerateAnimeVideoUseCase(
            config=config,
            storyboard_model=storyboard_model,
            image_generator=image_generator,
            video_generator=video_generator,
            asset_store=LocalAssetStore(),
            clip_merger=FfmpegClipMerger(),
            runtime_dependency=RuntimeDependencyChecker(),
        )
        reference_images, reference_image_labels = _collect_reference_images(
            reference_dir=args.reference_dir,
            logger=logger,
        )

        manifest = use_case.execute(
            GenerateAnimeVideoRequest(
                outline_file=args.outline_file,
                output_dir=args.output_dir,
                reference_images=reference_images,
                reference_image_labels=reference_image_labels,
            )
        )
        log_run_event(
            logger=logger,
            event="cli_manifest_ready",
            stage="cli",
            message="Run manifest ready for output",
            total_shots=manifest.total_shots,
            completed_shots=manifest.succeeded_shots,
            failed_shots=manifest.failed_shots,
        )
        render_manifest_output(
            manifest=manifest,
            output_format=args.output_format,
            manifest_path=args.output_dir / config.paths.run_manifest_file,
        )

        if manifest.run_status == "partial_failed":
            failed_ids = ", ".join(item.shot_id for item in manifest.failed_records) or "unknown"
            summary = (
                "[Nian-Kantoku Partial Failure] "
                f"succeeded={manifest.succeeded_shots}, failed={manifest.failed_shots}, "
                f"failed_shots={failed_ids}"
            )
            print(summary, file=sys.stderr)
            log_run_event(
                logger=logger,
                event="cli_partial_failure",
                stage="cli",
                message=summary,
                level=logging.WARNING,
                total_shots=manifest.total_shots,
                completed_shots=manifest.succeeded_shots,
                failed_shots=manifest.failed_shots,
            )
            return 2

        return 0
    except NianKantokuError as exc:
        log_run_event(
            logger=logger,
            event="cli_failed",
            stage="cli",
            message="CLI run failed with fatal error",
            level=logging.ERROR,
            error=str(exc),
        )
        print(f"[Nian-Kantoku Error] {exc}", file=sys.stderr)
        return 2
    finally:
        dashboard.stop(logger)


if __name__ == "__main__":
    raise SystemExit(main())
