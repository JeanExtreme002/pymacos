"""Unit tests for :mod:`macos.auth`. They run on any platform."""

import inspect

import pytest

import macos


def test_auth_argument_checks():
    with pytest.raises(ValueError, match="reason must not be empty"):
        macos.auth.confirm("  ")
    for reason in (None, 5, b"deploy"):
        with pytest.raises(TypeError, match="reason must be a str, not"):
            macos.auth.confirm(reason)
        with pytest.raises(TypeError, match="reason must be a str, not"):
            macos.auth.required(reason)  # when decorating, not at the first call


def test_a_bad_timeout_raises_before_the_prompt_shows(prompts):
    replies, _, sent = prompts
    for timeout in (0, -1, float("nan")):
        with pytest.raises(ValueError, match="timeout must be positive, or None"):
            macos.auth.confirm("deploy", timeout=timeout)
    assert not any(selector.startswith("evaluatePolicy:") for selector in sent)


def test_confirm_without_a_timeout_waits_for_the_answer(prompts, monkeypatch):
    import math

    from macos import _objc

    replies, _, _ = prompts
    waited = []

    def run_until(condition, timeout):
        waited.append(timeout)
        return condition()

    monkeypatch.setattr(_objc, "run_until", run_until)
    replies.append(True)
    assert macos.auth.confirm("deploy", timeout=None) is True and waited == [math.inf]


class _Replies(list):
    """The answers to come, plus the fake NSErrors the tests make up."""


@pytest.fixture
def prompts(monkeypatch):
    """
    LocalAuthentication faked: each prompt answers what ``replies`` holds next.

    ``None`` is no answer; a callable gets the list of reply blocks made so
    far and answers through them, for replies that come late or out of order.
    """
    from contextlib import nullcontext

    from macos import _objc, auth

    replies, blocks, sent = _Replies(), [], []

    errors = {}  # a fake NSError pointer -> (code, description)

    def send(receiver, selector, *args, **kwargs):
        sent.append(selector)
        if selector == "code":
            return errors[receiver][0]
        if selector == "localizedDescription":
            return errors[receiver][1]
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
    monkeypatch.setattr(_objc, "pystring", lambda text: text)
    replies.errors = errors
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


def test_confirm_from_a_callback_during_a_prompt_raises_instead_of_hanging(prompts):
    replies, blocks, _ = prompts
    nested = []

    def a_menu_item_clicked_meanwhile(made):
        # Run-loop callbacks run on this thread while it waits: a guarded one asks again.
        with pytest.raises(macos.MacOSError, match="already waiting for an answer on this thread") as caught:
            macos.auth.confirm("delete everything")
        nested.append(caught.value)
        made[-1](True, 0)  # then the first prompt is answered

    replies.extend([a_menu_item_clicked_meanwhile, False])
    assert macos.auth.confirm("deploy") is True and len(nested) == 1
    assert macos.auth.confirm("deploy") is False  # once it returned, asking works again


def test_confirm_from_other_threads_waits_its_turn(prompts):
    import threading

    replies, _, _ = prompts
    replies.extend([True, True])
    results = []
    threads = [threading.Thread(target=lambda: results.append(macos.auth.confirm("deploy"))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results == [True, True]


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


def test_required_takes_a_callable_without_a_signature(monkeypatch):
    import sys

    monkeypatch.setattr(macos.auth, "confirm", lambda reason, only_touch_id=False: True)
    try:
        inspect.signature(sys.getsizeof)
    except ValueError:
        pass  # what this test needs: a builtin that has none
    else:
        pytest.skip("sys.getsizeof has a signature on this Python")

    size = macos.auth.required("measure")(sys.getsizeof)
    assert size(0) == sys.getsizeof(0) and not hasattr(size, "__wrapped__")


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


def test_confirm_tells_declined_from_cant_ask(prompts):
    replies, blocks, _ = prompts
    replies.errors.update({11: (-2, "Canceled by user."), 12: (-1004, "User interaction is required."),
                           13: (-5, "Passcode not set."), 14: (-10, "Context invalidated.")})  # fmt: skip
    replies.extend([lambda made: made[-1](False, 11)])
    assert macos.auth.confirm("deploy") is False  # the user said no
    replies.extend([lambda made: made[-1](False, 12)])
    with pytest.raises(macos.NotSupportedError, match="can't ask for authentication here.*LAError -1004"):
        macos.auth.confirm("deploy")  # over SSH: nobody could have declined
    replies.extend([lambda made: made[-1](False, 13)])
    with pytest.raises(macos.NotSupportedError, match="Passcode not set"):
        macos.auth.confirm("deploy")
    replies.extend([lambda made: made[-1](False, 14)])
    with pytest.raises(macos.MacOSError, match="taken down"):
        macos.auth.confirm("deploy")
    replies.extend([True])
    assert macos.auth.confirm("deploy") is True  # and the next prompt is unaffected


def test_required_keeps_a_coroutine_function_one_and_asks_when_awaited(monkeypatch):
    import asyncio

    asked = []
    monkeypatch.setattr(macos.auth, "confirm", lambda reason, only_touch_id=False: asked.append(reason) or True)

    @macos.auth.required("deploy")
    async def deploy(target):
        return "deployed " + target

    assert inspect.iscoroutinefunction(deploy) and not hasattr(deploy, "__wrapped__")
    assert str(inspect.signature(deploy)) == "(target)"
    coroutine = deploy("prod")
    assert asked == []  # made, not awaited: no prompt yet
    assert asyncio.run(coroutine) == "deployed prod" and asked == ["deploy"]

    monkeypatch.setattr(macos.auth, "confirm", lambda reason, only_touch_id=False: False)
    with pytest.raises(macos.PermissionDeniedError):
        asyncio.run(deploy("prod"))


def test_required_refuses_an_async_generator_function():
    async def feed():
        yield 1

    with pytest.raises(TypeError, match="async generator"):
        macos.auth.required("read the feed")(feed)
