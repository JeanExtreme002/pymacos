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


def test_capture_permission_restricted_names_the_administrator(monkeypatch):
    monkeypatch.setattr(_capture, "request_permission", lambda media: False)
    monkeypatch.setattr(_capture, "_status", lambda media: _capture._RESTRICTED)

    with pytest.raises(macos.PermissionDeniedError, match="Camera is restricted on this Mac") as caught:
        _capture.require_permission(_capture.VIDEO)
    assert "administrator" in str(caught.value) and "restart" not in str(caught.value)


def test_capture_permission_allowed_just_as_the_wait_ends_does_not_raise(monkeypatch):
    # The prompt timed out, but the status read afterwards shows the user clicked Allow right then.
    monkeypatch.setattr(_capture, "request_permission", lambda media: False)
    monkeypatch.setattr(_capture, "_status", lambda media: _capture._AUTHORIZED)

    assert _capture.require_permission(_capture.AUDIO) is None


def test_capture_answer_is_settled_while_holding_the_lock(prompt):
    fake = prompt(None)
    seen = []

    class _Probe:
        """Records whether the lock is held while the answer is settled."""

        def __init__(self):
            self.granted = False
            self.done = self

        def set(self):
            seen.append((self.granted, _capture._lock.locked()))

        def is_set(self):
            return False

    probe = _Probe()
    _capture._handler(_capture.VIDEO)
    _capture._waiting[_capture.VIDEO].append(probe)
    fake.blocks[0](True)

    assert seen == [(True, True)] and _capture._waiting[_capture.VIDEO] == []
