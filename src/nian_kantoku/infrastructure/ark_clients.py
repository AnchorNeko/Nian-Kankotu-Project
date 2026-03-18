from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from nian_kantoku.application.exceptions import MissingDependencyError, PipelineExecutionError
from nian_kantoku.application.run_models import GeneratedImageReference, VideoTaskStatus

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
                part = item.get("text")
                if isinstance(part, str):
                    chunks.append(part)
            else:
                part = getattr(item, "text", None)
                if isinstance(part, str):
                    chunks.append(part)
        return "".join(chunks)
    if isinstance(content, dict):
        text = content.get("text")
        return text if isinstance(text, str) else ""
    text = getattr(content, "text", None)
    return text if isinstance(text, str) else ""


def _extract_duration(response: Any) -> Optional[float]:
    candidates = [
        _dig(response, "duration"),
        _dig(response, "duration_sec"),
        _dig(response, "output", "duration"),
        _dig(response, "output", "duration_sec"),
        _dig(response, "result", "duration"),
        _dig(response, "result", "duration_sec"),
    ]
    for value in candidates:
        if isinstance(value, (int, float)):
            return float(value)
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
    def generate_storyboard(self, *, model: str, prompt: str) -> str:
        try:
            response = self._client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:  # noqa: BLE001
            raise PipelineExecutionError(f"Storyboard model request failed: {exc}") from exc

        choices = _dig(response, "choices")
        if not isinstance(choices, list) or not choices:
            raise PipelineExecutionError("Storyboard model response missing non-empty choices list")

        message = _dig(choices[0], "message")
        if message is None:
            raise PipelineExecutionError("Storyboard model response missing message in first choice")

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
        reference_images: Sequence[str],
        seed: int | None,
        guidance_scale: float | None,
        optimize_prompt: bool | None,
    ) -> GeneratedImageReference:
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "response_format": "url",
            "size": f"{width}x{height}",
        }
        if reference_images:
            payload["image"] = list(reference_images)
        if seed is not None:
            payload["seed"] = seed
        if guidance_scale is not None:
            payload["guidance_scale"] = guidance_scale
        if optimize_prompt is not None:
            payload["optimize_prompt"] = optimize_prompt

        try:
            response = self._client.images.generate(**payload)
        except Exception as exc:  # noqa: BLE001
            raise PipelineExecutionError(f"Image generation request failed: {exc}") from exc

        data = _dig(response, "data")
        if not isinstance(data, list) or not data:
            raise PipelineExecutionError("Image model response missing non-empty data list")

        first = data[0]
        image_url = _dig(first, "url") or _dig(first, "image_url")
        if not isinstance(image_url, str) or not image_url.strip():
            raise PipelineExecutionError("Image model response missing image URL in first data item")

        return GeneratedImageReference(image_url=image_url)


class ArkVideoGeneratorAdapter(_ArkAdapterBase):
    def create_video_task(
        self,
        *,
        model: str,
        prompt: str,
        image_url: str,
    ) -> str:
        try:
            response = self._client.content_generation.tasks.create(
                model=model,
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            )
        except Exception as exc:  # noqa: BLE001
            raise PipelineExecutionError(f"Video task creation request failed: {exc}") from exc

        task_id = _dig(response, "id") or _dig(response, "task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            raise PipelineExecutionError("Video task creation response missing task id")
        return task_id

    def get_video_task_status(self, *, task_id: str) -> VideoTaskStatus:
        try:
            response = self._client.content_generation.tasks.get(task_id=task_id)
        except Exception as exc:  # noqa: BLE001
            raise PipelineExecutionError(f"Video task status request failed: {exc}") from exc

        raw_status = _dig(response, "status") or _dig(response, "task_status") or _dig(response, "state")
        if not isinstance(raw_status, str) or not raw_status.strip():
            raise PipelineExecutionError(
                f"Video task status response missing status string for task_id={task_id}"
            )

        raw_video_url = (
            _dig(response, "video_url")
            or _dig(response, "content", "video_url")
            or _dig(response, "output", "video_url")
            or _dig(response, "result", "video_url")
        )
        video_url: Optional[str]
        if raw_video_url is None:
            video_url = None
        elif isinstance(raw_video_url, str) and raw_video_url.strip():
            video_url = raw_video_url
        else:
            raise PipelineExecutionError(
                f"Video task status response has invalid video_url type for task_id={task_id}"
            )

        raw_error_message = _dig(response, "error", "message") or _dig(response, "error_message")
        error_message: Optional[str]
        if raw_error_message is None:
            error_message = None
        elif isinstance(raw_error_message, str):
            error_message = raw_error_message
        else:
            raise PipelineExecutionError(
                f"Video task status response has invalid error_message type for task_id={task_id}"
            )

        return VideoTaskStatus(
            task_id=task_id,
            status=raw_status,
            video_url=video_url,
            error_message=error_message,
            actual_duration_sec=_extract_duration(response),
        )
