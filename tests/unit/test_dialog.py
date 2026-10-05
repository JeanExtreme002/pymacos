"""Unit tests for :mod:`macos.dialog`. They run on any platform."""

from pathlib import Path

import pytest

import macos


def _script(args):
    """The AppleScript source of an osascript call (everything before "--")."""
    return "\n".join(args[i + 1] for i in range(args.index("--")) if args[i] == "-e")


def test_dialog_passes_text_as_arguments(fake_run):
    fake_run.stdout = "ok\nAlice\n"

    assert macos.dialog.prompt('Name? "quoted" -e', default="x", title="T", hidden=True) == "Alice"

    args = fake_run.args
    assert args[args.index("--") + 1:] == ['Name? "quoted" -e', "x", "T"]
    script = _script(args)
    assert "with hidden answer" in script and "Name?" not in script
    assert "activate" in script


@pytest.mark.parametrize("output, expected", [("ok\n", True), ("cancel\n", False), ("timeout\n", False)])
def test_dialog_confirm(fake_run, output, expected):
    fake_run.stdout = output

    assert macos.dialog.confirm("Delete?", ok="Delete", cancel="Keep", timeout=5) is expected
    assert "giving up after 5" in _script(fake_run.args)
    assert fake_run.args[-3:] == ["Delete?", "Delete", "Keep"]


def test_dialog_prompt_cancel_and_multiline(fake_run):
    fake_run.stdout = "cancel\n"
    assert macos.dialog.prompt("x") is None

    fake_run.stdout = "ok\nline 1\nline 2\n"
    assert macos.dialog.prompt("x") == "line 1\nline 2"


def test_dialog_choose(fake_run):
    fake_run.stdout = "ok\nPear\n"

    assert macos.dialog.choose(["Apple", "Pear"], prompt="Fruit?", default="Pear") == "Pear"
    assert fake_run.args[-5:] == ["Fruit?", "Pear", "", "Apple", "Pear"]
    assert "with title" not in _script(fake_run.args)

    macos.dialog.choose(["Apple", "Pear"], title="Fruits")
    assert fake_run.args[-3:] == ["Fruits", "Apple", "Pear"]
    assert "with title (item 3 of argv)" in _script(fake_run.args)

    fake_run.stdout = "cancel\n"
    assert macos.dialog.choose(["Apple"]) is None


@pytest.mark.parametrize(
    "options, default", [([], None), (["a\nb"], None), (["a"], "b")]
)
def test_dialog_choose_rejects_bad_options(options, default):
    with pytest.raises(ValueError):
        macos.dialog.choose(options, default=default)


def test_dialog_choose_files(fake_run, tmp_path):
    fake_run.stdout = "ok\n/a/one.pdf\0/b/two words.pdf\0\n"

    assert macos.dialog.choose_files(types=[".pdf", "public.image"], folder=tmp_path) == [
        Path("/a/one.pdf"),
        Path("/b/two words.pdf"),
    ]
    script = _script(fake_run.args)
    assert "with multiple selections allowed" in script and "of type fileTypes" in script
    assert fake_run.args[-2:] == ["pdf\npublic.image", str(tmp_path.resolve())]

    fake_run.stdout = "cancel\n"
    assert macos.dialog.choose_files() == []
    assert macos.dialog.choose_file() is None
    assert macos.dialog.choose_folder() is None


@pytest.mark.parametrize("timeout, seconds", [(0.1, 1), (0.5, 1), (1, 1), (1.4, 2), (2.5, 3)])
def test_dialog_timeouts_round_up_to_whole_seconds(fake_run, timeout, seconds):
    fake_run.stdout = "timeout\n"

    macos.dialog.confirm("x", timeout=timeout)
    assert "giving up after {}".format(seconds) in _script(fake_run.args)


def test_dialog_rejects_bad_timeout():
    with pytest.raises(ValueError):
        macos.dialog.confirm("x", timeout=0)


def test_dialog_chosen_paths_may_hold_newlines(fake_run):
    fake_run.stdout = "ok\n/a/first\nline.pdf\0/b/ends with\n\0\n"
    assert macos.dialog.choose_files() == [Path("/a/first\nline.pdf"), Path("/b/ends with\n")]

    fake_run.stdout = "ok\n/a/odd\nname.pdf\0\n"
    assert macos.dialog.choose_file() == Path("/a/odd\nname.pdf")
    fake_run.stdout = "ok\n/Users/me/new\nfolder/\0\n"
    assert macos.dialog.choose_folder() == Path("/Users/me/new\nfolder")
