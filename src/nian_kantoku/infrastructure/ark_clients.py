from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional, Sequence

from nian_kantoku.application.exceptions import MissingDependencyError, PipelineExecutionError
from nian_kantoku.domain.models import GeneratedImageReference, VideoTaskStatus

try:
    from volcenginesdkarkruntime import Ark
except Exception:  # noqa: BLE001
    Ark = None  # type: ignore[assignment]


def _dig(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        else:
            current = getattr(current, key, None)
        if current is None:
            return None
    return current


def _to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                chunks.append(str(item.get("text", "")))
            else:
                chunks.append(str(getattr(item, "text", "")))
        return "".join(chunks)
    if isinstance(content, dict):
        return str(content.get("text", ""))
    return str(content)


def _iter_nodes(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for sub_value in value.values():
            yield from _iter_nodes(sub_value)
    elif isinstance(value, list):
        for sub_value in value:
            yield from _iter_nodes(sub_value)
    else:
        for attr in ("__dict__",):
            nested = getattr(value, attr, None)
            if nested:
                yield from _iter_nodes(nested)


def _find_first_url(value: Any) -> Optional[str]:
    for node in _iter_nodes(value):
        if isinstance(node, str) and node.startswith("http"):
            return node
    return None


def _find_duration(value: Any) -> Optional[float]:
    for node in _iter_nodes(value):
        if isinstance(node, dict):
            for key, maybe_value in node.items():
                if "duration" in str(key).lower() and isinstance(
                    maybe_value, (int, float)
                ):
                    return float(maybe_value)
        elif hasattr(node, "duration"):
            maybe_value = getattr(node, "duration", None)
            if isinstance(maybe_value, (int, float)):
                return float(maybe_value)
    return None


class _ArkAdapterBase:
    def __init__(
        self,
        *,
        api_key: str,
        request_timeout_sec: int,
        client: Any = None,
    ) -> None:
        if client is not None:
            self._client = client
            return

        if Ark is None:
            raise MissingDependencyError(
                "volcengine-python-sdk[ark] is not installed. "
                "Install with: pip install 'volcengine-python-sdk[ark]'"
            )

        self._client = Ark(api_key=api_key, timeout=request_timeout_sec)


class ArkStoryboardModelAdapter(_ArkAdapterBase):
    def generate_storyboard(self, *, model: str, prompt: str, timeout_sec: int) -> str:
        del timeout_sec
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            if (
                "response_format.type" in error_text
                and "not supported by this model" in error_text
            ):
                response = self._client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                )
            else:
                raise
        choices = _dig(response, "choices") or []
        if not choices:
            raise PipelineExecutionError("No choices returned from storyboard model")
        message = _dig(choices[0], "message")
        content = _dig(message, "content")
        text = _to_text(content)
        if not text.strip():
            raise PipelineExecutionError("Storyboard model returned empty content")
        return text


class ArkImageGeneratorAdapter(_ArkAdapterBase):
    def generate_image(
        self,
        *,
        model: str,
        prompt: str,
        width: int,
        height: int,
        timeout_sec: int,
        reference_images: Sequence[str],
        seed: int | None,
        guidance_scale: float | None,
        optimize_prompt: bool | None,
    ) -> GeneratedImageReference:
        del timeout_sec
        size = f"{width}x{height}"
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "response_format": "url",
            "size": size,
        }
        if reference_images:
            payload["image"] = list(reference_images)
        if seed is not None:
            payload["seed"] = seed
        if guidance_scale is not None:
            payload["guidance_scale"] = guidance_scale
        if optimize_prompt is not None:
            payload["optimize_prompt"] = optimize_prompt

        response = self._generate_image_with_fallback(payload=payload)
        data = _dig(response, "data") or []
        if not data:
            raise PipelineExecutionError("Image model returned empty data list")

        first = data[0]
        image_url = _dig(first, "url") or _dig(first, "image_url")
        if not image_url:
            image_url = _find_first_url(first)

        if not image_url:
            raise PipelineExecutionError("Image model response does not include an image URL")
        return GeneratedImageReference(image_url=str(image_url))

    def _generate_image_with_fallback(self, *, payload: Dict[str, Any]) -> Any:
        fallback_order = ["image", "guidance_scale", "seed", "optimize_prompt"]
        logger = logging.getLogger("nian_kantoku.run")
        while True:
            try:
                return self._client.images.generate(**payload)
            except Exception as exc:  # noqa: BLE001
                if not _should_retry_image_with_fallback(exc):
                    raise
                removed = _pop_next_optional_param(payload=payload, fallback_order=fallback_order)
                if removed is None:
                    raise
                logger.warning(
                    "Image generation fallback activated, removed parameter '%s': %s",
                    removed,
                    exc,
                )


class ArkVideoGeneratorAdapter(_ArkAdapterBase):
    def create_video_task(
        self,
        *,
        model: str,
        prompt: str,
        image_url: str,
        duration_sec: float,
        width: int,
        height: int,
        fps: int,
        timeout_sec: int,
    ) -> str:
        del duration_sec, width, height, fps, timeout_sec

        response = self._client.content_generation.tasks.create(
            model=model,
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_url}},
            ],
        )

        task_id = _dig(response, "id") or _dig(response, "task_id")
        if not task_id:
            task_id = _find_first_task_id(response)

        if not task_id:
            raise PipelineExecutionError("Video task creation response has no task id")
        return str(task_id)

    def get_video_task_status(self, *, task_id: str, timeout_sec: int) -> VideoTaskStatus:
        del timeout_sec
        response = self._client.content_generation.tasks.get(task_id=task_id)

        status = (
            _dig(response, "status")
            or _dig(response, "task_status")
            or _dig(response, "state")
            or "unknown"
        )

        video_url = (
            _dig(response, "video_url")
            or _dig(response, "output", "video_url")
            or _dig(response, "result", "video_url")
        )
        if not video_url:
            video_url = _find_first_url(response)

        error_message = (
            _dig(response, "error", "message")
            or _dig(response, "message")
            or _dig(response, "error_message")
        )

        return VideoTaskStatus(
            task_id=task_id,
            status=str(status),
            video_url=str(video_url) if video_url else None,
            error_message=str(error_message) if error_message else None,
            actual_duration_sec=_find_duration(response),
        )


def _find_first_task_id(value: Any) -> Optional[str]:
    for node in _iter_nodes(value):
        if isinstance(node, dict):
            for key, maybe_value in node.items():
                if str(key).lower() in {"task_id", "id"} and isinstance(maybe_value, str):
                    return maybe_value
        else:
            for attr in ("task_id", "id"):
                maybe_value = getattr(node, attr, None)
                if isinstance(maybe_value, str):
                    return maybe_value
    return None


def _should_retry_image_with_fallback(exc: Exception) -> bool:
    text = str(exc).lower()
    indicators = (
        "not support",
        "unsupported",
        "unknown",
        "invalid",
        "unrecognized",
        "unexpected field",
        "unexpected argument",
        "bad request",
    )
    return any(item in text for item in indicators)


def _pop_next_optional_param(*, payload: Dict[str, Any], fallback_order: Sequence[str]) -> Optional[str]:
    for key in fallback_order:
        if key in payload:
            payload.pop(key)
            return key
    return None
