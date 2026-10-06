"""Unit tests for :mod:`macos.auth`. They run on any platform."""

import inspect

import pytest

import macos


def test_auth_argument_checks():
    with pytest.raises(ValueError, match="reason must not be empty"):
        macos.auth.confirm("  ")


@pytest.fixture
def prompts(monkeypatch):
    """
    LocalAuthentication faked: each prompt answers what ``replies`` holds next.

    ``None`` is no answer; a callable gets the list of reply blocks made so
    far and answers through them, for replies that come late or out of order.
    """
    from contextlib import nullcontext

    from macos import _objc, auth

    replies, blocks, sent = [], [], []

    def send(receiver, selector, *args, **kwargs):
        sent.append(selector)
        if selector.startswith("evaluatePolicy:"):
            assert args[2] == len(blocks)  # the current block, the newest
            answer = replies.pop(0)
            if callable(answer):
                answer(blocks)
            elif answer is not None:
                blocks[-1](answer, 0)

    def block(function, *signature):
        blocks.append(function)
        return len(blocks)

    monkeypatch.setattr(auth, "framework", lambda name: None)
    monkeypatch.setattr(auth, "_context", lambda: 1)
    monkeypatch.setattr(_objc, "send", send)
    monkeypatch.setattr(_objc, "nsstring", lambda text: text)
    monkeypatch.setattr(_objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(_objc, "run_until", lambda condition, timeout: condition())
    monkeypatch.setattr(_objc, "block", block)
    auth._handler.cache_clear()
    monkeypatch.setattr(auth, "_generation", [0])
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

    replies, blocks, sent = prompts
    replies.extend([None, False])

    assert macos.auth.confirm("deploy", timeout=0.01) is False
    assert "invalidate" in sent and auth._generation == [1]  # the unanswered prompt's block is retired
    blocks[0](True, 0)  # the dismissed prompt's reply, late: dropped
    assert auth._answers == []
    assert macos.auth.confirm("deploy") is False  # its own answer, not the stale True
    assert len(blocks) == 2


def test_a_late_success_after_the_next_denial_doesnt_confirm(prompts):
    replies, blocks, _ = prompts

    def denied_then_late_success(made):
        made[1](False, 0)  # the new prompt: denied
        made[0](True, 0)  # then the old, dismissed prompt's success arrives

    replies.extend([None, denied_then_late_success])

    assert macos.auth.confirm("deploy", timeout=0.01) is False
    assert macos.auth.confirm("deploy") is False


def test_an_interrupted_prompts_late_success_cant_confirm_the_next(prompts, monkeypatch):
    from macos import _objc, auth

    replies, blocks, sent = prompts

    def interrupted(condition, timeout):
        raise KeyboardInterrupt  # Ctrl-C while waiting for the answer

    monkeypatch.setattr(_objc, "run_until", interrupted)
    replies.append(None)
    with pytest.raises(KeyboardInterrupt):
        macos.auth.confirm("deploy")
    assert "invalidate" in sent and auth._generation == [1]  # its block retired

    monkeypatch.setattr(_objc, "run_until", lambda condition, timeout: condition())

    def late_success_then_denied(made):
        made[0](True, 0)  # the interrupted prompt's success, arriving during the next call
        made[1](False, 0)  # the next prompt: denied

    replies.append(late_success_then_denied)
    assert macos.auth.confirm("deploy") is False

    replies.append(lambda made: made[0](True, 0))  # only the stale success, no answer of its own
    assert macos.auth.confirm("deploy", timeout=0.01) is False


def test_required_hides_the_unguarded_function(monkeypatch):
    monkeypatch.setattr(macos.auth, "confirm", lambda reason, only_touch_id=False: False)

    @macos.auth.required("deploy")
    def deploy():
        """Deploy it."""
        return "deployed"

    assert not hasattr(deploy, "__wrapped__")
    assert str(inspect.signature(deploy)) == "()"  # the arguments it takes, though not the function itself
    assert (deploy.__name__, deploy.__doc__) == ("deploy", "Deploy it.")
    with pytest.raises(macos.PermissionDeniedError):
        inspect.unwrap(deploy)()


def test_a_guarded_callback_without_arguments_gets_no_event(monkeypatch):
    from macos import events

    monkeypatch.setattr(macos.auth, "confirm", lambda reason, only_touch_id=False: True)

    @macos.auth.required("lock up")
    def on_sleep():
        return "locked"

    @macos.auth.required("log it")
    def on_event(event):
        return event

    assert events._takes_event(on_sleep) is False and on_sleep() == "locked"
    assert events._takes_event(on_event) is True
