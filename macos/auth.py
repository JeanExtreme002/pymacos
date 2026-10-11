# -*- coding: utf-8 -*-

"""
Ask the user to confirm it's them, with Touch ID, their login password or their Apple Watch.

::

    if macos.auth.confirm("unlock the production credentials"):
        token = macos.keychain.get("deploy", "prod")

macOS shows its own prompt, and checks the fingerprint or the password
itself: the script only learns whether it succeeded. It's a check before a
sensitive action, not encryption: a Keychain item isn't locked behind it.
"""

import ctypes
import functools
import inspect
import threading
from functools import lru_cache
from typing import Any, Callable, List, NamedTuple, Optional, TypeVar

from . import _objc
from ._system import framework
from .errors import MacOSError, NotSupportedError, PermissionDeniedError

__all__ = ["confirm", "is_available", "required"]

_BIOMETRICS, _OWNER = 1, 2  # LAPolicyDeviceOwnerAuthenticationWithBiometrics, LAPolicyDeviceOwnerAuthentication


def _policy(only_touch_id: bool) -> int:
    return _BIOMETRICS if only_touch_id else _OWNER


def _context() -> int:
    """An ``LAContext`` owned by the caller, who releases it (``_objc.new`` would be autoreleased)."""
    framework("LocalAuthentication")
    return _objc.send(_objc.send(_objc.cls("LAContext"), "alloc"), "init")


def is_available(*, only_touch_id: bool = False) -> bool:
    """
    Whether :func:`confirm` can ask, without asking.

    With ``only_touch_id=True``, whether Touch ID is set up (and not locked
    out after failed tries). Otherwise it's always true, as the login password
    works on any Mac.
    """
    context = _context()
    with _objc.autorelease_pool():
        try:
            return bool(
                _objc.send(
                    context,
                    "canEvaluatePolicy:error:",
                    _policy(only_touch_id),
                    None,
                    argtypes=(_objc.NSInteger, ctypes.c_void_p),
                    restype=_objc.BOOL,
                )
            )
        finally:
            _objc.send(context, "release", restype=None)


# One reply block serves prompt after prompt: _objc.block keeps each block
# alive for good, so a new one per confirm() would leak. The block files the
# answer in _answers, and _prompt lets one prompt at a time wait on it (macOS
# shows one at a time anyway). A prompt given up on (timeout) still replies
# once, later, in any order with the next prompt's reply: so its block is
# retired (_generation moves on), and what it says then goes nowhere. Only
# timeouts make a new block.
_prompt = threading.Lock()
_waiting: List[Optional[int]] = [None]  # the thread whose prompt is up
_state = threading.Lock()
_answers: List["_Answer"] = []
_generation = [0]
_DRAIN = 2.0  # seconds to wait for a dismissed prompt's own reply

# LAError codes (LAPublicDefines.h). The user's doing, or the prompt's: the answer is "no".
_DECLINED = {
    -1,  # kLAErrorAuthenticationFailed: wrong password or fingerprint, too many times
    -2,  # kLAErrorUserCancel
    -3,  # kLAErrorUserFallback: asked for the password instead, and only_touch_id refused
    -4,  # kLAErrorSystemCancel: another app came to the front, the Mac slept...
    -9,  # kLAErrorAppCancel: the prompt was invalidated (a timeout here)
}
_INVALID_CONTEXT = -10  # kLAErrorInvalidContext: the context was invalidated before the prompt: a bug here
# Everything else means the question couldn't be asked: no passcode set (-5), no biometry
# (-6, -7), biometry locked out (-8), no companion (-11), biometry not paired or disconnected
# (-12, -13), no user session to show a prompt in (-1004, over SSH or in a service)...


class _Answer(NamedTuple):
    success: bool
    code: Optional[int]
    message: Optional[str]


def _reply(generation: int, success: bool, error: int) -> None:
    code = message = None
    if not success and error:
        try:
            code = int(_objc.send(error, "code", restype=_objc.NSInteger))
            message = _objc.pystring(_objc.send(error, "localizedDescription"))
        except Exception:  # an exception must not cross back into Objective-C: a "no" without a reason
            pass
    with _state:
        if generation == _generation[0]:  # a retired block's reply answers nothing
            _answers.append(_Answer(bool(success), code, message))


@lru_cache(maxsize=None)
def _handler(generation: int) -> int:
    """The reply block of ``generation``, ``void (^)(BOOL success, NSError *error)``, made once: blocks live for good."""

    def reply(success: bool, error: int) -> None:
        _reply(generation, success, error)

    return _objc.block(reply, b"v@?B@", ctypes.c_bool, ctypes.c_void_p)


def _outcome(answer: "_Answer") -> bool:
    """What a prompt's reply means: ``True``, ``False`` (declined), or an error when it couldn't be asked."""
    if answer.success or answer.code is None or answer.code in _DECLINED:
        return answer.success
    reason = answer.message or "LocalAuthentication error {}".format(answer.code)
    if answer.code == _INVALID_CONTEXT:
        raise MacOSError("the authentication prompt was taken down before it was answered: {}".format(reason))
    raise NotSupportedError(
        "macOS can't ask for authentication here: {} (LAError {})".format(reason.rstrip("."), answer.code)
    )


def _answered() -> bool:
    with _state:
        return bool(_answers)


def confirm(reason: str, *, only_touch_id: bool = False, timeout: float = 120.0) -> bool:
    """
    Show macOS's prompt to confirm it's the Mac's owner, and return whether they did.

    ``reason`` completes the prompt's sentence: *"Python wants to <reason>"*.
    The user can place their finger on Touch ID, or type their login password
    (or approve on their Apple Watch); ``only_touch_id=True`` accepts only the
    fingerprint. Cancelling, failing, or ``timeout`` seconds without an answer
    return ``False``. Raises :class:`~macos.errors.NotSupportedError` when
    ``only_touch_id=True`` and Touch ID isn't available, and when macOS can't
    ask at all: no password set, biometry locked out, or no user session to
    show the prompt in (over SSH, in a service), so a "no" always means the
    user declined.

    One prompt at a time: calls from other threads wait their turn. A call
    made while this thread is already waiting for an answer (from a menu
    bar item or a hotkey's callback, which run during that wait) raises
    :class:`~macos.errors.MacOSError` instead of waiting forever.
    """
    if not reason.strip():
        raise ValueError("reason must not be empty: macOS shows it in the prompt")
    framework("LocalAuthentication")  # before the reply block: NotSupportedError outside macOS
    if only_touch_id and not is_available(only_touch_id=True):
        raise NotSupportedError("Touch ID isn't set up on this Mac (or is locked after failed tries)")
    me = threading.get_ident()
    if _waiting[0] == me:
        # Called from a run-loop callback (a menu item, a hotkey...) while this
        # thread waits on a prompt: waiting for that prompt's lock would never end.
        raise MacOSError("confirm() is already waiting for an answer on this thread; ask again once it returns")
    with _prompt:
        _waiting[0] = me
        try:
            with _state:
                del _answers[:]
                generation = _generation[0]
            handler = _handler(generation)
            context = _context()
            try:
                with _objc.autorelease_pool():
                    _objc.send(
                        context,
                        "evaluatePolicy:localizedReason:reply:",
                        _policy(only_touch_id),
                        _objc.nsstring(reason),
                        handler,
                        argtypes=(_objc.NSInteger, _objc.id, ctypes.c_void_p),
                        restype=None,
                    )
                if not _objc.run_until(_answered, timeout):
                    _objc.send(context, "invalidate", restype=None)  # takes the prompt away
                    # Its reply still comes, once: wait for it here, or retire the
                    # block, so that reply can't answer the next prompt.
                    _objc.run_until(_answered, _DRAIN)
                    with _state:
                        if not _answers:
                            _generation[0] += 1
                        del _answers[:]
                    return False
                with _state:
                    answer = _answers.pop(0)
            except BaseException:
                # Interrupted (Ctrl-C...) while the prompt may still be up: retire
                # its block first, so whatever it answers later goes nowhere, then
                # take the prompt away.
                with _state:
                    _generation[0] += 1
                    del _answers[:]
                try:
                    _objc.send(context, "invalidate", restype=None)
                except Exception:
                    pass  # the interruption is what the caller needs to see
                raise
            finally:
                _objc.send(context, "release", restype=None)
            # Answered: what it means (an error here is the answer, not an interruption to clean up after).
            return _outcome(answer)
        finally:
            _waiting[0] = None


_Function = TypeVar("_Function", bound=Callable[..., Any])


def required(reason: str, *, only_touch_id: bool = False) -> Callable[[_Function], _Function]:
    """
    Ask to confirm with :func:`confirm` each time the decorated function is called, before it runs.

    ::

        @macos.auth.required("deploy to production")
        def deploy():
            ...

    When the user doesn't confirm, the call raises
    :class:`~macos.errors.PermissionDeniedError` and the function doesn't run.

    It's a check that the user is present, within this process; not a
    security boundary against code running in it, which can always call
    the original function some other way. The wrapper keeps the function's
    name and docstring but not ``__wrapped__``, so at least
    :func:`inspect.unwrap` doesn't skip the prompt by accident.
    """
    if not reason.strip():
        raise ValueError("reason must not be empty: macOS shows it in the prompt")

    def decorate(function: _Function) -> _Function:
        @functools.wraps(function)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            if not confirm(reason, only_touch_id=only_touch_id):
                raise PermissionDeniedError("{} wasn't confirmed".format(reason))
            return function(*args, **kwargs)

        # functools.wraps sets __wrapped__, which inspect.unwrap() and
        # signature() follow straight to the unguarded function. The signature
        # is kept on its own, without the function: code that inspects the
        # arguments (events.run() passing the event or not) sees the same.
        delattr(guarded, "__wrapped__")
        try:
            guarded.__signature__ = inspect.signature(function)  # type: ignore[attr-defined]
        except (TypeError, ValueError):
            pass  # some builtins have none to keep: the wrapper's own (*args, **kwargs) stands
        return guarded  # type: ignore[return-value]

    return decorate
