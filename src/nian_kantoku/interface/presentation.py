from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from nian_kantoku.application.run_models import RunManifest


def render_manifest_output(
    *,
    manifest: RunManifest,
    output_format: str,
    manifest_path: Path,
) -> None:
    if output_format == "json":
        print(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2))
        return
    _render_pretty_manifest(manifest=manifest, manifest_path=manifest_path)


def _render_pretty_manifest(*, manifest: RunManifest, manifest_path: Path) -> None:
    diagnostics = _load_diagnostics(manifest.artifacts.shot_diagnostics_file)
    try:
        from rich import box
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except Exception:  # noqa: BLE001
        _render_plain_manifest(manifest=manifest, manifest_path=manifest_path, diagnostics=diagnostics)
        return

    console = Console()

    summary = Table(show_header=False, box=box.SIMPLE_HEAVY)
    summary.add_row("Run Status", manifest.run_status)
    summary.add_row("Shots", str(manifest.total_shots))
    summary.add_row("Succeeded", str(manifest.succeeded_shots))
    summary.add_row("Failed", str(manifest.failed_shots))
    summary.add_row("Failed Shot IDs", ", ".join(manifest.failed_shot_ids) or "-")
    summary.add_row(
        "Character Designs",
        _format_design_summary(manifest.character_design_summary.to_dict()),
    )
    summary.add_row(
        "Background Designs",
        _format_design_summary(manifest.background_design_summary.to_dict()),
    )
    summary.add_row("Merged Video", manifest.merged_video_path or "-")
    summary.add_row("Manifest File", str(manifest_path))
    summary.add_row("Diagnostics File", manifest.artifacts.shot_diagnostics_file)
    console.print(Panel(summary, title="Nian Kantoku Run Summary", border_style="cyan"))

    if not diagnostics:
        console.print(Panel("No shot diagnostics found in diagnostics file.", border_style="yellow"))
        return

    for shot in diagnostics:
        shot_table = Table(show_header=False, box=box.SIMPLE)
        shot_table.add_row("Status", str(shot.get("status", "-")))
        shot_table.add_row("Planned Duration", f"{float(shot.get('planned_duration_sec', 0.0)):.2f}s")
        shot_table.add_row("Image Model", str(shot.get("image_model") or "-"))
        shot_table.add_row("Video Model", str(shot.get("video_model") or "-"))
        shot_table.add_row("Image Params", _format_image_params(shot))
        shot_table.add_row("Render Params", _format_render_params(shot))
        shot_table.add_row("Character IDs", _format_list(shot.get("character_ids")))
        shot_table.add_row("Background ID", str(shot.get("background_id") or "-"))
        shot_table.add_row("Reference Anchors", _format_list(shot.get("reference_images_used")))
        shot_table.add_row(
            "Consistency References",
            _format_list(shot.get("consistency_references_used")),
        )
        shot_table.add_row("Keyframe Path", str(shot.get("keyframe_path") or "-"))
        shot_table.add_row("Keyframe URL", str(shot.get("image_url") or "-"))
        shot_table.add_row("Video Task ID", str(shot.get("video_task_id") or "-"))
        shot_table.add_row("Clip Path", str(shot.get("clip_path") or "-"))
        if shot.get("failed_stage"):
            shot_table.add_row("Failed Stage", str(shot.get("failed_stage")))
        if shot.get("error_message"):
            shot_table.add_row("Error", str(shot.get("error_message")))

        prompt_table = Table(show_header=False, box=box.MINIMAL)
        prompt_table.add_row("Storyboard Image Prompt", str(shot.get("storyboard_image_prompt") or "-"))
        prompt_table.add_row("Effective Keyframe Prompt", str(shot.get("effective_image_prompt") or "-"))
        prompt_table.add_row("Storyboard Video Prompt", str(shot.get("storyboard_video_prompt") or "-"))
        prompt_table.add_row("Effective Storyboard Video Prompt", str(shot.get("effective_video_prompt") or "-"))

        status = str(shot.get("status", ""))
        status_border = "green" if status == "succeeded" else "red" if status == "failed" else "yellow"
        shot_index = int(shot.get("shot_index", 0) or 0)
        shot_id = str(shot.get("shot_id") or "unknown")
        console.print(
            Panel(
                shot_table,
                title=f"Shot {shot_index:02d} · {shot_id}",
                border_style=status_border,
            )
        )
        console.print(Panel(prompt_table, title="Prompt Diagnostics", border_style="magenta"))


def _render_plain_manifest(*, manifest: RunManifest, manifest_path: Path, diagnostics: List[Dict[str, Any]]) -> None:
    print("Nian Kantoku Run Summary")
    print(f"- run_status: {manifest.run_status}")
    print(f"- total_shots: {manifest.total_shots}")
    print(f"- succeeded_shots: {manifest.succeeded_shots}")
    print(f"- failed_shots: {manifest.failed_shots}")
    print(f"- failed_shot_ids: {', '.join(manifest.failed_shot_ids) or '-'}")
    print(f"- character_design_summary: {_format_design_summary(manifest.character_design_summary.to_dict())}")
    print(f"- background_design_summary: {_format_design_summary(manifest.background_design_summary.to_dict())}")
    print(f"- merged_video_path: {manifest.merged_video_path or '-'}")
    print(f"- diagnostics_file: {manifest.artifacts.shot_diagnostics_file}")
    print(f"- manifest_file: {manifest_path}")

    if not diagnostics:
        print("- shot_diagnostics: none")
        return

    for shot in diagnostics:
        shot_index = int(shot.get("shot_index", 0) or 0)
        shot_id = str(shot.get("shot_id") or "unknown")
        print(f"\nShot {shot_index:02d} · {shot_id} · status={shot.get('status', '-')}")
        print(f"planned_duration_sec: {float(shot.get('planned_duration_sec', 0.0)):.2f}")
        print(f"image_model: {shot.get('image_model') or '-'}")
        print(f"video_model: {shot.get('video_model') or '-'}")
        print(f"image_params: {_format_image_params(shot)}")
        print(f"render_params: {_format_render_params(shot)}")
        print(f"character_ids: {_format_list(shot.get('character_ids'))}")
        print(f"background_id: {shot.get('background_id') or '-'}")
        print(f"reference_anchors: {_format_list(shot.get('reference_images_used'))}")
        print(f"consistency_references: {_format_list(shot.get('consistency_references_used'))}")
        print(f"keyframe_path: {shot.get('keyframe_path') or '-'}")
        print(f"keyframe_url: {shot.get('image_url') or '-'}")
        print(f"video_task_id: {shot.get('video_task_id') or '-'}")
        print(f"clip_path: {shot.get('clip_path') or '-'}")
        if shot.get("failed_stage"):
            print(f"failed_stage: {shot.get('failed_stage')}")
        if shot.get("error_message"):
            print(f"error: {shot.get('error_message')}")
        print("storyboard_image_prompt:")
        print(shot.get("storyboard_image_prompt") or "-")
        print("effective_keyframe_prompt:")
        print(shot.get("effective_image_prompt") or "-")
        print("storyboard_video_prompt:")
        print(shot.get("storyboard_video_prompt") or "-")
        print("effective_storyboard_video_prompt:")
        print(shot.get("effective_video_prompt") or "-")


def _load_diagnostics(path_text: str) -> List[Dict[str, Any]]:
    diagnostics_path = Path(path_text)
    if not diagnostics_path.exists():
        return []

    rows: List[Dict[str, Any]] = []
    for line in diagnostics_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _format_image_params(shot: Dict[str, Any]) -> str:
    return (
        f"seed={shot.get('image_seed')}, guidance_scale={shot.get('image_guidance_scale')}, "
        f"optimize_prompt={shot.get('image_optimize_prompt')}"
    )


def _format_render_params(shot: Dict[str, Any]) -> str:
    width = shot.get("render_width")
    height = shot.get("render_height")
    fps = shot.get("render_fps")
    if width is None or height is None or fps is None:
        return "-"
    return f"{width}x{height}@{fps}fps"


def _format_list(values: Any) -> str:
    if not isinstance(values, list):
        return "-"
    text_values = [str(item) for item in values if str(item)]
    return ", ".join(text_values) if text_values else "-"


def _format_design_summary(summary: Dict[str, Any]) -> str:
    total = int(summary.get("total", 0) or 0)
    succeeded = int(summary.get("succeeded", 0) or 0)
    return f"{succeeded}/{total} succeeded"
