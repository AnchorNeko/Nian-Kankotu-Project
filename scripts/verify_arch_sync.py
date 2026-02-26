#!/usr/bin/env python3
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import List

import yaml

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from nian_kantoku import ARCH_CONTRACT_VERSION  # noqa: E402


def _extract_contract(markdown_text: str) -> dict:
    match = re.search(
        r"```yaml\s*(architecture_contract:\s*.*?\n)```",
        markdown_text,
        flags=re.DOTALL,
    )
    if not match:
        raise RuntimeError("architecture_contract YAML block not found in docs/architecture.md")

    payload = yaml.safe_load(match.group(1))
    if not isinstance(payload, dict) or "architecture_contract" not in payload:
        raise RuntimeError("Invalid architecture_contract YAML block")
    return payload["architecture_contract"]


def _collect_ports_from_code(ports_file: Path) -> List[str]:
    tree = ast.parse(ports_file.read_text(encoding="utf-8"))
    port_names: List[str] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.endswith("Port"):
            port_names.append(node.name)
    return sorted(port_names)


def main() -> int:
    errors: List[str] = []

    architecture_doc = ROOT / "docs" / "architecture.md"
    config_file = ROOT / "config" / "settings.yaml"
    ports_file = ROOT / "src" / "nian_kantoku" / "application" / "ports.py"
    prompt_file = ROOT / "src" / "nian_kantoku" / "application" / "prompt_templates.py"

    contract = _extract_contract(architecture_doc.read_text(encoding="utf-8"))
    config = yaml.safe_load(config_file.read_text(encoding="utf-8"))

    doc_version = str(contract.get("version", "")).strip()
    if doc_version != ARCH_CONTRACT_VERSION:
        errors.append(
            f"Contract version mismatch: docs={doc_version}, code={ARCH_CONTRACT_VERSION}"
        )

    config_version = str(config.get("architecture_contract_version", "")).strip()
    if config_version != ARCH_CONTRACT_VERSION:
        errors.append(
            f"Contract version mismatch: config={config_version}, code={ARCH_CONTRACT_VERSION}"
        )

    contract_ports = sorted(contract.get("ports", []))
    code_ports = _collect_ports_from_code(ports_file)
    if contract_ports != code_ports:
        errors.append(f"Port list mismatch: docs={contract_ports}, code={code_ports}")

    policy = contract.get("policy", {})
    if policy.get("overlong_storyboard_handling") != "regenerate_offending_shots":
        errors.append("Policy mismatch: overlong_storyboard_handling must be regenerate_offending_shots")

    if policy.get("final_video_duration_hard_limit") is not False:
        errors.append("Policy mismatch: final_video_duration_hard_limit must be false")
    if policy.get("background_consistency_granularity") != "location_level":
        errors.append("Policy mismatch: background_consistency_granularity must be location_level")
    if policy.get("design_asset_failure_handling") != "fail_fast_before_shot_loop":
        errors.append("Policy mismatch: design_asset_failure_handling must be fail_fast_before_shot_loop")
    if policy.get("style_anchor_strategy") != (
        "shot_related_character_background_designs_plus_user_refs_plus_previous_successful_keyframe"
    ):
        errors.append("Policy mismatch: style_anchor_strategy must include shot-related design anchors")

    consistency_assets = config.get("consistency_assets")
    if not isinstance(consistency_assets, dict):
        errors.append("Config key missing: consistency_assets must be a mapping")
    else:
        for required_key in (
            "max_main_characters",
            "max_backgrounds",
            "max_character_refs_per_shot",
            "fail_on_missing_design_assets",
        ):
            if required_key not in consistency_assets:
                errors.append(f"Config key missing: consistency_assets.{required_key}")

    paths = config.get("paths")
    if not isinstance(paths, dict):
        errors.append("Config key missing: paths must be a mapping")
    else:
        for required_key in (
            "character_sheet_file",
            "background_sheet_file",
            "character_designs_dir",
            "background_designs_dir",
        ):
            if required_key not in paths:
                errors.append(f"Config key missing: paths.{required_key}")

    prompt_text = prompt_file.read_text(encoding="utf-8")
    if "duration_sec <=" not in prompt_text:
        errors.append("Prompt rule missing: duration_sec <= constraint")

    if "split it into more shots" not in prompt_text:
        errors.append("Prompt rule missing: split dense content into more shots")
    if "character_ids" not in prompt_text or "background_id" not in prompt_text:
        errors.append("Prompt rule missing: storyboard schema must include character_ids/background_id")
    if "build_character_extraction_prompt" not in prompt_text:
        errors.append("Prompt function missing: build_character_extraction_prompt")
    if "build_effective_video_prompt" not in prompt_text:
        errors.append("Prompt function missing: build_effective_video_prompt")

    if errors:
        print("Architecture sync check failed:")
        for item in errors:
            print(f"- {item}")
        return 1

    print("Architecture sync check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
