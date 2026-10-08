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
