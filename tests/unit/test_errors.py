"""Unit tests for the exception hierarchy and command errors."""

import pytest

import macos


def test_failed_command_raises_command_error(fake_run):
    fake_run.returncode = 1
    fake_run.stderr = "execution error\n"

    with pytest.raises(macos.CommandError) as info:
        macos.notify("x")

    assert info.value.returncode == 1
    assert info.value.stderr == "execution error"
    assert isinstance(info.value, macos.MacOSError)


@pytest.mark.parametrize(
    "error",
    [
        macos.CommandError(["say", "-v", "x"], 1, "boom\n"),
        macos.KeychainError(-25300, "The item could not be found."),
        macos.KeychainError(-25300),
    ],
)
def test_errors_survive_pickling(error):
    import pickle

    copy = pickle.loads(pickle.dumps(error))

    assert type(copy) is type(error)
    assert str(copy) == str(error)
    assert vars(copy) == vars(error)


def test_error_messages():
    assert str(macos.CommandError(["say"], 1, "boom\n")) == "'say' exited with status 1: boom"
    assert str(macos.KeychainError(-25300)) == "Keychain error (OSStatus -25300)"


def test_permission_error_is_also_the_builtin():
    assert issubclass(macos.PermissionDeniedError, PermissionError)
    assert issubclass(macos.AppNotFoundError, LookupError)


def test_run_bytes_hands_over_the_output_as_written(fake_run):
    from macos import _system

    fake_run.stdout = b"<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>Caf\xe9\r\n"  # not UTF-8, CRLF kept
    assert _system.run_bytes(["mdls", "-plist", "-", "x"]) == fake_run.stdout
    assert "text" not in fake_run.calls[-1]  # bytes from the command, never decoded on the way

    fake_run.returncode, fake_run.stderr = 1, b"mdls: no such file"
    with pytest.raises(macos.CommandError, match="no such file"):
        _system.run_bytes(["mdls", "x"])


def test_run_decodes_bytes_whichever_way_it_was_asked(fake_run):
    from macos import _system

    fake_run.stdout = "Caf\xe9".encode("utf-8")  # bytes, even where text was asked for
    assert _system.run(["sw_vers"]) == "Café"  # decoded: never the "b'...'" str() would make of it
    assert _system.run(["ls"], exact_newlines=True) == "Café"


def test_main_thread_error_is_also_a_runtime_error():
    # menubar raised RuntimeError before, and the other checks MacOSError: a handler for either still catches it.
    assert issubclass(macos.MainThreadError, RuntimeError) and issubclass(macos.MainThreadError, macos.MacOSError)


def test_command_errors_keep_the_arguments_out_of_repr():
    # The default repr prints self.args, that is the whole command line: a URL with a token (browser),
    # a dialog's default text, a notification... str() names the command only, and so must repr().
    error = macos.CommandError(["open", "https://example.com/?token=s3cret"], 1, "boom\n")
    assert repr(error) == "CommandError('open', returncode=1, stderr='boom')"
    assert str(error) == "'open' exited with status 1: boom"
    assert error.cmd == ["open", "https://example.com/?token=s3cret"] and error.args[0] == error.cmd  # still there
    timeout = macos.CommandTimeoutError(["osascript", "-e", "display dialog", "--", "s3cret"], 30)
    assert repr(timeout) == "CommandTimeoutError('osascript', timeout=30)"
    assert str(timeout) == "'osascript' didn't finish within 30 seconds"
    missing = macos.ShortcutNotFoundError(["shortcuts", "run", "s3cret name"], 1, "not found")
    assert repr(missing) == "ShortcutNotFoundError('shortcuts', returncode=1, stderr='not found')"
    for shown in (repr(error), repr(timeout), repr(missing), str(error), str(timeout), str(missing)):
        assert "s3cret" not in shown


@pytest.mark.parametrize(
    "error",
    [
        macos.CommandError(["say", "-v", "x"], 1, "boom\n"),
        macos.CommandTimeoutError(["say", "-v", "x"], 2.5),
        macos.ShortcutNotFoundError(["shortcuts", "run", "x"], 1, ""),
    ],
)
def test_command_errors_still_cross_a_pickle(error):
    import pickle

    copy = pickle.loads(pickle.dumps(error))

    assert type(copy) is type(error) and copy.cmd == error.cmd
    if isinstance(error, OSError):  # not the command and its time limit taken for an errno and its message
        assert (error.errno, error.strerror, copy.errno, copy.strerror) == (None, None, None, None)
    assert (str(copy), repr(copy)) == (str(error), repr(error))


def test_command_errors_name_an_empty_or_one_shot_command():
    # str() mustn't raise, or a traceback says "<exception str() failed>" in place of the failure.
    for error in (macos.CommandError([], 1, "boom"), macos.CommandTimeoutError([], 1)):
        assert "<command>" in str(error) and "<command>" in repr(error)
    error = macos.CommandError((a for a in ["say", "x"]), 1)  # a generator, read once
    assert error.cmd == ["say", "x"] and error.args[0] == error.cmd
    assert str(error) == "'say' exited with status 1"
    timeout = macos.CommandTimeoutError(iter(["say", "x"]), 2)
    assert timeout.cmd == ["say", "x"] and str(timeout) == "'say' didn't finish within 2 seconds"


@pytest.mark.parametrize(
    "returncode, shown",
    [(-9, "'say' was killed by SIGKILL"), (-15, "'say' was killed by SIGTERM"), (-200, "'say' was killed by signal 200")],
)
def test_command_error_says_a_signal_killed_the_command(returncode, shown):
    # subprocess reports a child killed by signal N as returncode -N: it never exited with a status.
    assert str(macos.CommandError(["say", "x"], returncode)) == shown
    assert str(macos.CommandError(["say", "x"], returncode, "bye\n")) == shown + ": bye"
    assert repr(macos.CommandError(["say"], returncode)) == "CommandError('say', returncode={}, stderr='')".format(returncode)


def test_app_launch_timeout_is_still_an_app_not_found_error():
    # apps.open raised AppNotFoundError when a launch didn't show up: its handlers keep catching it,
    # and so does ``except TimeoutError``, as for every other wait that ran out of time.
    import pickle

    from macos.errors import AppLaunchTimeoutError

    error = AppLaunchTimeoutError("'Foo' didn't show up within 5 seconds")
    assert isinstance(error, macos.AppNotFoundError) and isinstance(error, LookupError)
    assert isinstance(error, TimeoutError) and isinstance(error, macos.MacOSError)
    assert str(error) == "'Foo' didn't show up within 5 seconds" and error.errno is None
    copy = pickle.loads(pickle.dumps(error))
    assert type(copy) is AppLaunchTimeoutError and str(copy) == str(error)
