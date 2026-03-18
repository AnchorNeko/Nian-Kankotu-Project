from __future__ import annotations

from types import SimpleNamespace

import pytest

from nian_kantoku.application.exceptions import PipelineExecutionError
from nian_kantoku.infrastructure.ark_clients import (
    ArkImageGeneratorAdapter,
    ArkStoryboardModelAdapter,
    ArkVideoGeneratorAdapter,
)


class _FakeChatCompletions:
    def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"shots": [{"shot_id": "shot_001", "duration_sec": 5, "story_beat": "x", "camera_instruction": "y", "image_prompt": "z", "video_prompt": "v", "character_ids": ["character_001"], "background_id": "background_001"}], "backgrounds": [{"background_id": "background_001", "display_name": "street", "location_description": "street", "visual_constraints": "warm", "design_prompt": "street prompt"}]}'
                    )
                )
            ]
        )


class _FailingChatCompletions:
    def create(self, **kwargs):
        raise Exception("upstream request failed")  # noqa: BLE001


class _FakeImages:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        self.kwargs = kwargs
        return SimpleNamespace(data=[SimpleNamespace(url="http://example.com/image.png")])


class _InvalidImages:
    def generate(self, **kwargs):
        del kwargs
        return SimpleNamespace(data=[SimpleNamespace()])


class _FakeTaskAPI:
    def __init__(self):
        self.create_kwargs = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return SimpleNamespace(task_id="task_123")

    def get(self, **kwargs):
        del kwargs
        return SimpleNamespace(
            status="succeeded",
            result=SimpleNamespace(video_url="http://example.com/clip.mp4", duration=22.5),
        )


class _FakeTaskAPIWithContentVideo:
    def create(self, **kwargs):
        del kwargs
        return SimpleNamespace(task_id="task_456")

    def get(self, **kwargs):
        del kwargs
        return SimpleNamespace(
            status="succeeded",
            content=SimpleNamespace(video_url="http://example.com/content_clip.mp4"),
            duration=5,
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeChatCompletions())
        self.images = _FakeImages()
        self.content_generation = SimpleNamespace(tasks=_FakeTaskAPI())


def test_storyboard_adapter_request_shape() -> None:
    client = _FakeClient()
    adapter = ArkStoryboardModelAdapter(api_key="x", request_timeout_sec=1, client=client)

    result = adapter.generate_storyboard(model="m", prompt="p")

    assert "shots" in result
    assert client.chat.completions.kwargs["model"] == "m"
    assert client.chat.completions.kwargs["messages"][0]["content"] == "p"


def test_storyboard_adapter_fails_when_upstream_error() -> None:
    client = _FakeClient()
    client.chat = SimpleNamespace(completions=_FailingChatCompletions())
    adapter = ArkStoryboardModelAdapter(api_key="x", request_timeout_sec=1, client=client)

    with pytest.raises(PipelineExecutionError):
        adapter.generate_storyboard(model="m", prompt="p")


def test_image_adapter_request_shape() -> None:
    client = _FakeClient()
    adapter = ArkImageGeneratorAdapter(api_key="x", request_timeout_sec=1, client=client)

    image = adapter.generate_image(
        model="m",
        prompt="p",
        width=1280,
        height=720,
        reference_images=["data:image/png;base64,abc"],
        seed=7,
        guidance_scale=4.5,
        optimize_prompt=False,
    )

    assert image.image_url == "http://example.com/image.png"
    assert client.images.kwargs["size"] == "1280x720"
    assert client.images.kwargs["seed"] == 7
    assert client.images.kwargs["guidance_scale"] == 4.5
    assert client.images.kwargs["image"] == ["data:image/png;base64,abc"]


def test_image_adapter_fails_when_response_missing_url() -> None:
    client = _FakeClient()
    client.images = _InvalidImages()
    adapter = ArkImageGeneratorAdapter(api_key="x", request_timeout_sec=1, client=client)

    with pytest.raises(PipelineExecutionError):
        adapter.generate_image(
            model="m",
            prompt="p",
            width=1280,
            height=720,
            reference_images=["data:image/png;base64,abc"],
            seed=7,
            guidance_scale=4.5,
            optimize_prompt=False,
        )


def test_video_adapter_task_lifecycle_mapping() -> None:
    client = _FakeClient()
    adapter = ArkVideoGeneratorAdapter(api_key="x", request_timeout_sec=1, client=client)

    task_id = adapter.create_video_task(
        model="video-model",
        prompt="shot prompt",
        image_url="http://example.com/image.png",
    )
    status = adapter.get_video_task_status(task_id=task_id)

    assert task_id == "task_123"
    assert status.status == "succeeded"
    assert status.video_url == "http://example.com/clip.mp4"
    assert client.content_generation.tasks.create_kwargs["content"][0]["type"] == "text"


def test_video_adapter_reads_video_url_from_content_block() -> None:
    client = _FakeClient()
    client.content_generation = SimpleNamespace(tasks=_FakeTaskAPIWithContentVideo())
    adapter = ArkVideoGeneratorAdapter(api_key="x", request_timeout_sec=1, client=client)

    task_id = adapter.create_video_task(
        model="video-model",
        prompt="shot prompt",
        image_url="http://example.com/image.png",
    )
    status = adapter.get_video_task_status(task_id=task_id)

    assert task_id == "task_456"
    assert status.status == "succeeded"
    assert status.video_url == "http://example.com/content_clip.mp4"
