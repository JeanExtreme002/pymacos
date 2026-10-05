"""Unit tests for the Camera and Microphone permissions."""

import pytest

import macos
from macos import _capture


def test_capture_permission_denied(monkeypatch):
    monkeypatch.setattr(_capture, "request_permission", lambda media: False)
    monkeypatch.setattr(_capture, "_status", lambda media: _capture._DENIED)

    with pytest.raises(macos.PermissionDeniedError, match="Camera permission"):
        _capture.require_permission(_capture.VIDEO)
    with pytest.raises(macos.PermissionDeniedError, match="Microphone permission"):
        _capture.require_permission(_capture.AUDIO)


class _FakeObjC:
    """Stands in for the Objective-C bridge: the prompt is shown, and answered (or not) by ``answer``."""

    id = object()
    NSInteger = int

    def __init__(self, answer):
        self.answer = answer
        self.blocks = []
        self.requests = 0

    def block(self, function, signature, *argtypes):
        self.blocks.append(function)
        return len(self.blocks)

    def cls(self, name):
        return name

    def nsstring(self, text):
        return text

    def send(self, receiver, selector, *args, **kwargs):
        assert selector == "requestAccessForMediaType:completionHandler:"
        self.requests += 1
        if self.answer is not None:
            self.blocks[args[1] - 1](self.answer)

    def autorelease_pool(self):
        import contextlib

        return contextlib.nullcontext()

    def run_until(self, done, timeout):
        return done()


@pytest.fixture
def prompt(monkeypatch):
    def make(answer):
        fake = _FakeObjC(answer)
        monkeypatch.setattr(_capture, "_objc", fake)
        monkeypatch.setattr(_capture, "_handlers", {})
        monkeypatch.setattr(_capture, "_status", lambda media: _capture._NOT_DETERMINED)
        return fake

    return make


def test_capture_prompt_left_unanswered_is_a_timeout_not_a_denial(prompt):
    fake = prompt(None)  # the user never answers

    with pytest.raises(macos.PromptTimeoutError, match="no answer to the Camera permission prompt") as caught:
        _capture.require_permission(_capture.VIDEO)
    assert isinstance(caught.value, TimeoutError) and isinstance(caught.value, macos.MacOSError)
    assert not isinstance(caught.value, macos.PermissionDeniedError)
    assert _capture._waiting[_capture.VIDEO] == []  # the call that gave up doesn't wait any more
    assert fake.requests == 1


def test_capture_prompt_handler_is_made_once_per_media(prompt):
    fake = prompt(True)

    assert _capture.request_permission(_capture.AUDIO) is True
    assert _capture.request_permission(_capture.AUDIO) is True
    assert _capture.request_permission(_capture.VIDEO) is True
    assert len(fake.blocks) == 2 and fake.requests == 3  # one block for each media, not one per call
