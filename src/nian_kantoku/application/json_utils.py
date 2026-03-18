from __future__ import annotations

import json
import re
from typing import Any, Dict


_JSON_OBJECT_PATTERN = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def extract_json_object_text(raw_text: str) -> str:
    cleaned = raw_text.strip()
    if not cleaned:
        raise ValueError("Model output is empty")

    code_fence_match = _JSON_OBJECT_PATTERN.search(cleaned)
    if code_fence_match:
        return code_fence_match.group(1)

    if cleaned.startswith("{") and cleaned.endswith("}"):
        return cleaned

    first = cleaned.find("{")
    last = cleaned.rfind("}")
    if first == -1 or last == -1 or first >= last:
        raise ValueError("Model output does not contain a valid JSON object")

    return cleaned[first : last + 1]


def parse_json_object(raw_text: str) -> Dict[str, Any]:
    json_text = extract_json_object_text(raw_text)
    payload = json.loads(json_text)
    if not isinstance(payload, dict):
        raise ValueError("Model JSON output must be an object")
    return payload
