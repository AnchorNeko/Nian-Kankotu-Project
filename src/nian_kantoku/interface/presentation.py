from __future__ import annotations

import json
from pathlib import Path

from nian_kantoku.domain.models import RunManifest, ShotDiagnosticsRecord


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
    try:
        from rich import box
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
    except Exception:  # noqa: BLE001
        _render_plain_manifest(manifest=manifest, manifest_path=manifest_path)
        return

    console = Console()

    summary = Table(show_header=False, box=box.SIMPLE_HEAVY)
    summary.add_row("Run Status", manifest.run_status)
    summary.add_row("Shots", str(manifest.total_shots))
    summary.add_row("Succeeded", str(manifest.succeeded_shots))
    summary.add_row("Failed", str(manifest.failed_shots))
    summary.add_row(
        "Character Designs",
        _format_design_summary(manifest.character_designs),
    )
    summary.add_row(
        "Background Designs",
        _format_design_summary(manifest.background_designs),
    )
    summary.add_row("Merged Video", manifest.merged_video_path or "-")
    summary.add_row("Manifest File", str(manifest_path))
    console.print(Panel(summary, title="Nian Kantoku Run Summary", border_style="cyan"))

    diagnostics = manifest.shot_diagnostics
    if not diagnostics:
        console.print(Panel("No shot diagnostics found in manifest.", border_style="yellow"))
        return

    for shot in diagnostics:
        shot_table = Table(show_header=False, box=box.SIMPLE)
        shot_table.add_row("Status", shot.status)
        shot_table.add_row("Planned Duration", f"{shot.planned_duration_sec:.2f}s")
        shot_table.add_row("Image Model", shot.image_model or "-")
        shot_table.add_row("Video Model", shot.video_model or "-")
        shot_table.add_row("Image Params", _format_image_params(shot))
        shot_table.add_row("Render Params", _format_render_params(shot))
        shot_table.add_row("Character IDs", _format_list(shot.character_ids))
        shot_table.add_row("Background ID", shot.background_id or "-")
        shot_table.add_row("Reference Anchors", _format_list(shot.reference_images_used))
        shot_table.add_row(
            "Consistency References",
            _format_list(shot.consistency_references_used),
        )
        shot_table.add_row("Keyframe Path", shot.keyframe_path or "-")
        shot_table.add_row("Keyframe URL", shot.image_url or "-")
        shot_table.add_row("Video Task ID", shot.video_task_id or "-")
        shot_table.add_row("Clip Path", shot.clip_path or "-")
        if shot.failed_stage:
            shot_table.add_row("Failed Stage", shot.failed_stage)
        if shot.error_message:
            shot_table.add_row("Error", shot.error_message)

        prompt_table = Table(show_header=False, box=box.MINIMAL)
        prompt_table.add_row("Storyboard Image Prompt", shot.storyboard_image_prompt or "-")
        prompt_table.add_row("Effective Keyframe Prompt", shot.effective_image_prompt or "-")
        prompt_table.add_row("Storyboard Video Prompt", shot.storyboard_video_prompt or "-")
        prompt_table.add_row("Effective Storyboard Video Prompt", shot.effective_video_prompt or "-")

        status_border = "green" if shot.status == "succeeded" else "red" if shot.status == "failed" else "yellow"
        console.print(
            Panel(
                shot_table,
                title=f"Shot {shot.shot_index:02d} · {shot.shot_id}",
                border_style=status_border,
            )
        )
        console.print(Panel(prompt_table, title="Prompt Diagnostics", border_style="magenta"))


def _render_plain_manifest(*, manifest: RunManifest, manifest_path: Path) -> None:
    print("Nian Kantoku Run Summary")
    print(f"- run_status: {manifest.run_status}")
    print(f"- total_shots: {manifest.total_shots}")
    print(f"- succeeded_shots: {manifest.succeeded_shots}")
    print(f"- failed_shots: {manifest.failed_shots}")
    print(f"- character_designs: {_format_design_summary(manifest.character_designs)}")
    print(f"- background_designs: {_format_design_summary(manifest.background_designs)}")
    print(f"- merged_video_path: {manifest.merged_video_path or '-'}")
    print(f"- manifest_file: {manifest_path}")

    if not manifest.shot_diagnostics:
        print("- shot_diagnostics: none")
        return

    for shot in manifest.shot_diagnostics:
        print(f"\nShot {shot.shot_index:02d} · {shot.shot_id} · status={shot.status}")
        print(f"planned_duration_sec: {shot.planned_duration_sec:.2f}")
        print(f"image_model: {shot.image_model or '-'}")
        print(f"video_model: {shot.video_model or '-'}")
        print(f"image_params: {_format_image_params(shot)}")
        print(f"render_params: {_format_render_params(shot)}")
        print(f"character_ids: {_format_list(shot.character_ids)}")
        print(f"background_id: {shot.background_id or '-'}")
        print(f"reference_anchors: {_format_list(shot.reference_images_used)}")
        print(f"consistency_references: {_format_list(shot.consistency_references_used)}")
        print(f"keyframe_path: {shot.keyframe_path or '-'}")
        print(f"keyframe_url: {shot.image_url or '-'}")
        print(f"video_task_id: {shot.video_task_id or '-'}")
        print(f"clip_path: {shot.clip_path or '-'}")
        if shot.failed_stage:
            print(f"failed_stage: {shot.failed_stage}")
        if shot.error_message:
            print(f"error: {shot.error_message}")
        print("storyboard_image_prompt:")
        print(shot.storyboard_image_prompt or "-")
        print("effective_keyframe_prompt:")
        print(shot.effective_image_prompt or "-")
        print("storyboard_video_prompt:")
        print(shot.storyboard_video_prompt or "-")
        print("effective_storyboard_video_prompt:")
        print(shot.effective_video_prompt or "-")


def _format_image_params(shot: ShotDiagnosticsRecord) -> str:
    return (
        f"seed={shot.image_seed}, guidance_scale={shot.image_guidance_scale}, "
        f"optimize_prompt={shot.image_optimize_prompt}"
    )


def _format_render_params(shot: ShotDiagnosticsRecord) -> str:
    if shot.render_width is None or shot.render_height is None or shot.render_fps is None:
        return "-"
    return f"{shot.render_width}x{shot.render_height}@{shot.render_fps}fps"


def _format_list(values: list[str]) -> str:
    return ", ".join(values) if values else "-"


def _format_design_summary(records: list) -> str:
    if not records:
        return "0/0 succeeded"
    succeeded = sum(1 for item in records if item.status == "succeeded")
    return f"{succeeded}/{len(records)} succeeded"
