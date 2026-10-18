"""Unit tests for :mod:`macos.shortcuts`. They run on any platform."""

import os
import subprocess
from pathlib import Path

import pytest

import macos


def test_shortcut_text_input_goes_through_a_temporary_file(commands):
    commands.answers["run"] = (0, "Hello\n", "")

    assert macos.shortcuts.run("Translate", input="Olá") == "Hello"

    args = commands.calls[-1]
    assert args[:2] == ["shortcuts", "run"] and args[-2:] == ["--", "Translate"]
    assert commands.text_input == "Olá"
    assert not os.path.exists(args[args.index("--input-path") + 1])


def test_shortcut_file_inputs_and_output(commands, tmp_path):
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    first.touch()
    second.touch()

    assert macos.shortcuts.run("Make GIF", input=[first, second], output=tmp_path / "out.gif") is None
    assert commands.calls[-1] == [
        "shortcuts", "run",
        "--input-path", str(first), "--input-path", str(second),
        "--output-path", str(tmp_path / "out.gif"),
        "--", "Make GIF",
    ]


def test_shortcut_missing_input_file(commands, tmp_path):
    with pytest.raises(FileNotFoundError):
        macos.shortcuts.run("Resize", input=tmp_path / "missing.png")
    assert commands.calls == []


def test_shortcut_not_found_checks_the_list(commands):
    commands.answers["run"] = (1, "", "Error: Não foi possível encontrar o atalho")  # localized
    commands.answers["shortcuts list --show-identifiers"] = (0, "Other (1234-ABCD)\n", "")

    with pytest.raises(macos.ShortcutNotFoundError) as info:
        macos.shortcuts.run("Missing")
    assert isinstance(info.value, LookupError)


def test_shortcut_text_input_file_goes_even_when_the_run_fails(commands, tmp_path, monkeypatch):
    monkeypatch.setattr(macos.shortcuts.tempfile, "tempdir", str(tmp_path))
    commands.answers["run"] = (1, "", "Error: no")
    commands.answers["shortcuts list --show-identifiers"] = (0, "Fails (1234-ABCD)\n", "")
    with pytest.raises(macos.CommandError):
        macos.shortcuts.run("Fails", input="text")
    assert os.listdir(str(tmp_path)) == []  # the temporary file is gone
    # Even when the paths given after it are missing.
    with pytest.raises(FileNotFoundError):
        macos.shortcuts.run("Fails", input=[tmp_path / "missing.png"])
    assert os.listdir(str(tmp_path)) == []


def test_shortcut_failure_when_the_listing_fails_too_keeps_the_run_error(commands):
    commands.answers["run"] = (1, "", "Error: the run's own message")
    commands.answers["shortcuts list --show-identifiers"] = (1, "", "listing broke")

    with pytest.raises(macos.CommandError, match="the run's own message") as info:
        macos.shortcuts.run("Any")
    assert not isinstance(info.value, macos.ShortcutNotFoundError)


def test_shortcut_failure_of_an_existing_shortcut_is_a_command_error(commands):
    commands.answers["run"] = (1, "", "Error: something else")
    commands.answers["shortcuts list --show-identifiers"] = (0, "Broken (1234-ABCD)\n", "")

    with pytest.raises(macos.CommandError) as info:
        macos.shortcuts.run("Broken")
    assert not isinstance(info.value, macos.ShortcutNotFoundError)


def test_shortcut_list(commands):
    commands.answers["shortcuts list --folder-name=Work"] = (0, "One\nTwo\n\n", "")

    assert macos.shortcuts.list(folder="Work") == ["One", "Two"]
    assert commands.calls[-1] == ["shortcuts", "list", "--folder-name=Work"]


def test_shortcut_names_and_folders_that_look_like_options_stay_values(commands, tmp_path, monkeypatch):
    macos.shortcuts.run("--help")
    assert commands.calls[-1] == ["shortcuts", "run", "--", "--help"]

    commands.answers["shortcuts list --folder-name=-x"] = (0, "One\n", "")
    macos.shortcuts.list(folder="-x")
    assert commands.calls[-1] == ["shortcuts", "list", "--folder-name=-x"]

    monkeypatch.chdir(tmp_path)
    (tmp_path / "-i.png").touch()
    macos.shortcuts.run("Resize", input=[Path("-i.png")], output="-o.png")
    assert commands.calls[-1] == [
        "shortcuts", "run", "--input-path", str(tmp_path / "-i.png"), "--output-path", str(tmp_path / "-o.png"), "--", "Resize"
    ]


def test_shortcut_timeout(fake_run, monkeypatch):
    from macos import _system

    def slow(args, **kwargs):
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    macos.shortcuts.run("Quick", timeout=5)
    assert fake_run.calls[-1]["timeout"] == 5
    monkeypatch.setattr(_system.subprocess, "run", slow)
    with pytest.raises(macos.errors.CommandTimeoutError):
        macos.shortcuts.run("Slow", timeout=0.1)


def test_shortcut_that_deletes_its_text_input_still_returns_its_output(commands, monkeypatch):
    from macos import _system

    def run(args, **kwargs):
        os.remove(args[args.index("--input-path") + 1])  # a shortcut that cleans up its input itself
        return subprocess.CompletedProcess(args, 0, "Done\n", "")

    monkeypatch.setattr(_system.subprocess, "run", run)
    assert macos.shortcuts.run("Tidy", input="text") == "Done"  # not FileNotFoundError from the clean-up


def test_listing_shortcuts_never_hangs(fake_run):
    macos.shortcuts.list()
    assert fake_run.calls[-1]["timeout"] == macos.shortcuts._LIST_TIMEOUT


def test_a_failed_run_keeps_its_error_when_listing_times_out(fake_run, monkeypatch):
    from macos import shortcuts

    def run(args, timeout=None, **kwargs):
        if args[:2] == ["shortcuts", "list"]:
            raise macos.CommandTimeoutError(args, shortcuts._LIST_TIMEOUT)
        raise macos.CommandError(args, 1, "the shortcut failed")

    monkeypatch.setattr(shortcuts, "_run", run)
    with pytest.raises(macos.CommandError, match="the shortcut failed"):
        macos.shortcuts.run("Broken")  # the run's own error, not the listing's timeout


def test_shortcut_text_output_keeps_its_line_endings(commands):
    commands.answers["run"] = (0, b"a,b\r\nc,d\r\xff\n", b"")

    assert macos.shortcuts.run("Fetch CSV") == "a,b\r\nc,d\r\ufffd"  # only the command's own newline goes

    # The docstring names the endings as text, not as control characters.
    assert r"``\r\n``" in macos.shortcuts.run.__doc__
    assert "\r" not in macos.shortcuts.run.__doc__


def test_shortcut_list_of_a_missing_folder_raises(commands):
    commands.answers["shortcuts list --folders"] = (0, "Work (1234-ABCD)\nHome (5678-EFGH)\n", "")

    with pytest.raises(LookupError):
        macos.shortcuts.list(folder="Wrok")
    assert commands.calls[-1] == ["shortcuts", "list", "--folders", "--show-identifiers"]

    # An empty folder is no error, by name (in any case) or identifier.
    assert macos.shortcuts.list(folder="Work") == []
    assert macos.shortcuts.list(folder="work") == []
    assert macos.shortcuts.list(folder="5678-EFGH") == []


def test_shortcut_list_none_folder_and_full_folders_ask_nothing_more(commands):
    assert macos.shortcuts.list(folder="none") == []  # the shortcuts in no folder
    assert commands.calls == [["shortcuts", "list", "--folder-name=none"]]

    commands.answers["shortcuts list --folder-name=Work"] = (0, "One\n", "")
    assert macos.shortcuts.list(folder="Work") == ["One"]
    assert commands.calls[-1] == ["shortcuts", "list", "--folder-name=Work"]


def test_shortcut_list_keeps_an_empty_answer_when_the_folders_cant_be_listed(commands):
    commands.answers["shortcuts list --folders"] = (1, "", "listing broke")

    assert macos.shortcuts.list(folder="Work") == []


@pytest.mark.parametrize("value", [b"hello", bytearray(b"hello"), 42, [7], [b"a.png"]])
def test_shortcut_input_of_another_type_is_a_clear_type_error(commands, value):
    with pytest.raises(TypeError, match="input"):
        macos.shortcuts.run("X", input=value)
    assert commands.calls == []


def test_shortcut_input_paths_may_come_from_any_iterable(commands, tmp_path):
    (tmp_path / "a.png").touch()

    macos.shortcuts.run("Resize", input=(path for path in [tmp_path / "a.png"]))
    assert commands.calls[-1] == ["shortcuts", "run", "--input-path", str(tmp_path / "a.png"), "--", "Resize"]
