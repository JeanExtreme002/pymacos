"""Unit tests for :mod:`macos.auth`. They run on any platform."""

import pytest

import macos


def test_auth_argument_checks():
    with pytest.raises(ValueError, match="reason must not be empty"):
        macos.auth.confirm("  ")


@pytest.fixture
def prompts(monkeypatch):
    """LocalAuthentication faked: each prompt answers what ``replies`` holds next (``None``: no answer)."""
    from contextlib import nullcontext

    from macos import _objc, auth

    replies, blocks, sent = [], [], []

    def send(receiver, selector, *args, **kwargs):
        sent.append(selector)
        if selector.startswith("evaluatePolicy:"):
            assert args[2] == "the-block"
            answer = replies.pop(0)
            if answer is not None:
                auth._reply(answer, 0)

    monkeypatch.setattr(auth, "framework", lambda name: None)
    monkeypatch.setattr(auth, "_context", lambda: 1)
    monkeypatch.setattr(_objc, "send", send)
    monkeypatch.setattr(_objc, "nsstring", lambda text: text)
    monkeypatch.setattr(_objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_objc, "run_until", lambda condition, timeout: condition())
    monkeypatch.setattr(_objc, "block", lambda *args: blocks.append(args) or "the-block")
    auth._handler.cache_clear()
    monkeypatch.setattr(auth, "_stale", [0])
    yield replies, blocks, sent
    auth._handler.cache_clear()
    del auth._answers[:]


def test_confirm_makes_one_reply_block_for_every_prompt(prompts):
    replies, blocks, _ = prompts
    replies.extend([True, False, True])

    assert [macos.auth.confirm("deploy") for _ in range(3)] == [True, False, True]
    assert len(blocks) == 1  # blocks live for good: one per call would leak


def test_a_late_reply_cant_answer_the_next_prompt(prompts):
    from macos import auth

    replies, _, sent = prompts
    replies.extend([None, False])

    assert macos.auth.confirm("deploy", timeout=0.01) is False
    assert "invalidate" in sent and auth._stale == [1]
    auth._reply(True, 0)  # the dismissed prompt's reply, late: dropped
    assert auth._stale == [0] and auth._answers == []
    assert macos.auth.confirm("deploy") is False  # its own answer, not the stale True


def test_required_hides_the_unguarded_function(monkeypatch):
    import inspect

    monkeypatch.setattr(macos.auth, "confirm", lambda reason, only_touch_id=False: False)

    @macos.auth.required("deploy")
    def deploy():
        """Deploy it."""
        return "deployed"

    assert not hasattr(deploy, "__wrapped__")
    assert (deploy.__name__, deploy.__doc__) == ("deploy", "Deploy it.")
    with pytest.raises(macos.PermissionDeniedError):
        inspect.unwrap(deploy)()
