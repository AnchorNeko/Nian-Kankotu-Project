from __future__ import annotations

from types import SimpleNamespace

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
                        content='{"shots": [{"shot_id": "shot_001", "duration_sec": 5, "story_beat": "x", "camera_instruction": "y", "image_prompt": "z", "video_prompt": "v"}]}'
                    )
                )
            ]
        )


class _FallbackChatCompletions:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if "response_format" in kwargs:
            raise Exception(  # noqa: BLE001
                "response_format.type is not supported by this model"
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{\"shots\": [{\"shot_id\": \"shot_001\", \"duration_sec\": 5, \"story_beat\": \"x\", \"camera_instruction\": \"y\", \"image_prompt\": \"z\", \"video_prompt\": \"v\"}]}'
                    )
                )
            ]
        )


class _FakeImages:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        self.kwargs = kwargs
        return SimpleNamespace(data=[SimpleNamespace(url="http://example.com/image.png")])


class _FallbackImages:
    def __init__(self):
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        if "image" in kwargs:
            raise Exception("unsupported parameter: image")  # noqa: BLE001
        return SimpleNamespace(data=[SimpleNamespace(url="http://example.com/image.png")])


class _FakeTaskAPI:
    def __init__(self):
        self.create_kwargs = None

    def create(self, **kwargs):
        self.create_kwargs = kwargs
        return SimpleNamespace(task_id="task_123")

    def get(self, **kwargs):
        return SimpleNamespace(
            status="succeeded",
            result=SimpleNamespace(video_url="http://example.com/clip.mp4", duration=22.5),
        )


class _FakeClient:
    def __init__(self):
        self.chat = SimpleNamespace(completions=_FakeChatCompletions())
        self.images = _FakeImages()
        self.content_generation = SimpleNamespace(tasks=_FakeTaskAPI())


def test_storyboard_adapter_request_shape() -> None:
    client = _FakeClient()
    adapter = ArkStoryboardModelAdapter(api_key="x", request_timeout_sec=1, client=client)

    result = adapter.generate_storyboard(model="m", prompt="p", timeout_sec=1)

    assert "shots" in result
    assert client.chat.completions.kwargs["response_format"]["type"] == "json_object"


def test_storyboard_adapter_falls_back_when_json_object_unsupported() -> None:
    client = _FakeClient()
    client.chat = SimpleNamespace(completions=_FallbackChatCompletions())
    adapter = ArkStoryboardModelAdapter(api_key="x", request_timeout_sec=1, client=client)

    result = adapter.generate_storyboard(model="m", prompt="p", timeout_sec=1)

    assert "shots" in result
    assert len(client.chat.completions.calls) == 2
    assert "response_format" in client.chat.completions.calls[0]
    assert "response_format" not in client.chat.completions.calls[1]


def test_image_adapter_request_shape() -> None:
    client = _FakeClient()
    adapter = ArkImageGeneratorAdapter(api_key="x", request_timeout_sec=1, client=client)

    image = adapter.generate_image(
        model="m",
        prompt="p",
        width=1280,
        height=720,
        timeout_sec=1,
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


def test_image_adapter_fallback_removes_unsupported_optional_params() -> None:
    client = _FakeClient()
    client.images = _FallbackImages()
    adapter = ArkImageGeneratorAdapter(api_key="x", request_timeout_sec=1, client=client)

    image = adapter.generate_image(
        model="m",
        prompt="p",
        width=1280,
        height=720,
        timeout_sec=1,
        reference_images=["data:image/png;base64,abc"],
        seed=7,
        guidance_scale=4.5,
        optimize_prompt=False,
    )

    assert image.image_url == "http://example.com/image.png"
    assert len(client.images.calls) >= 2
    assert "image" in client.images.calls[0]
    assert "image" not in client.images.calls[-1]


def test_video_adapter_task_lifecycle_mapping() -> None:
    client = _FakeClient()
    adapter = ArkVideoGeneratorAdapter(api_key="x", request_timeout_sec=1, client=client)

    task_id = adapter.create_video_task(
        model="video-model",
        prompt="shot prompt",
        image_url="http://example.com/image.png",
        duration_sec=7,
        width=1280,
        height=720,
        fps=24,
        timeout_sec=1,
    )
    status = adapter.get_video_task_status(task_id=task_id, timeout_sec=1)

    assert task_id == "task_123"
    assert status.status == "succeeded"
    assert status.video_url == "http://example.com/clip.mp4"
    assert client.content_generation.tasks.create_kwargs["content"][0]["type"] == "text"
