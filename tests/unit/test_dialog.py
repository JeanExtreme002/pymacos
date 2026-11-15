"""Unit tests for :mod:`macos.dialog`. They run on any platform."""

import io
import subprocess
import time
from pathlib import Path

import pytest

import macos
from macos import _system


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


class _Dialog:
    """A fake osascript showing a dialog: says so on stderr, then answers, fails, or waits out its time."""

    def __init__(self, first_line=b"pymacos: the dialog shows\n", output=b"", errors=b"", returncode=0, answers=True):
        self.stderr = io.BytesIO(first_line)
        self.output, self.errors, self.returncode, self.answers = output, errors, returncode, answers
        self.waited, self.killed, self.args = [], False, None

    def __call__(self, args, **options):
        self.args = list(args)
        return self

    def poll(self):
        return None if not (self.answers or self.killed) else self.returncode

    def communicate(self, timeout=None):
        if self.killed:
            return b"", b""
        self.waited.append(timeout)
        if not self.answers:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.output, self.errors

    def kill(self):
        self.killed, self.returncode = True, -9


@pytest.fixture
def dialog(monkeypatch):
    def use(fake):
        monkeypatch.setattr(_system.sys, "platform", "darwin")
        monkeypatch.setattr(_system.subprocess, "Popen", fake)
        monkeypatch.setattr(macos.dialog.select, "select", lambda read, write, error, timeout: (read, [], []))
        return fake

    return use


@pytest.mark.parametrize(
    "show, cancelled",
    [
        (lambda: macos.dialog.choose(["Apple", "Pear"], timeout=2.5), None),
        (lambda: macos.dialog.choose_file(timeout=2.5), None),
        (lambda: macos.dialog.choose_files(timeout=2.5), []),
        (lambda: macos.dialog.choose_folder(timeout=2.5), None),
    ],
)
def test_the_list_and_pickers_close_as_cancelled_after_their_timeout(dialog, show, cancelled):
    # AppleScript can't give up on them: osascript is stopped at the deadline, which takes the dialog away.
    fake = dialog(_Dialog(answers=False))

    assert show() == cancelled
    assert fake.killed
    # Whole seconds, rounded up as for the other dialogs, from the moment the dialog says it shows: not from
    # osascript's start, as coming to the front takes it two seconds, which the dialog would lose.
    assert fake.waited == [3]
    assert 'log "pymacos: the dialog shows"' in _script(fake.args)


def test_a_warning_before_the_dialog_shows_keeps_the_timeout(dialog):
    # osascript, or a framework, may write a warning as it comes to the front: the time still starts at the
    # line saying the dialog shows, and the dialog doesn't wait forever.
    fake = dialog(_Dialog(first_line=b"some warning\nanother one\npymacos: the dialog shows\n", answers=False))

    assert macos.dialog.choose(["Apple"], timeout=2) is None
    assert fake.waited == [2] and fake.killed


def test_the_warnings_before_a_failure_are_in_its_error(dialog):
    dialog(_Dialog(first_line=b"some warning\n", errors=b"execution error: broken (-2700)\n", returncode=1))

    with pytest.raises(macos.MacOSError, match="-2700"):
        macos.dialog.choose(["Apple"], timeout=2)


def test_an_answer_before_the_timeout_comes_back(dialog):
    fake = dialog(_Dialog(output=b"ok\nPear\n"))

    assert macos.dialog.choose(["Apple", "Pear"], timeout=30) == "Pear"
    assert not fake.killed


def test_a_dialog_that_fails_before_it_shows_raises(dialog):
    # The script's error comes first on stderr, rather than the line saying the dialog shows.
    dialog(_Dialog(first_line=b"execution error: Can't get item 4 of argv. (-1728)\n", returncode=1))

    with pytest.raises(macos.MacOSError, match="-1728"):
        macos.dialog.choose(["Apple"], timeout=30)


def test_a_dialog_that_never_shows_is_given_up_on(dialog, monkeypatch):
    fake = dialog(_Dialog(first_line=b"", answers=False))
    monkeypatch.setattr(macos.dialog.select, "select", lambda read, write, error, timeout: ([], [], []))

    with pytest.raises(macos.CommandTimeoutError):
        macos.dialog.choose(["Apple"], timeout=30)
    assert fake.killed


def test_the_list_and_pickers_wait_with_no_timeout_given(fake_run):
    fake_run.stdout = "ok\nPear\n"

    macos.dialog.choose(["Apple", "Pear"])

    assert fake_run.calls[-1]["timeout"] is None


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 2 ** 29])
def test_the_list_and_pickers_refuse_a_timeout_that_isnt_one(fake_run, timeout):
    with pytest.raises(ValueError, match="timeout"):
        macos.dialog.choose(["Apple"], timeout=timeout)
    with pytest.raises(ValueError, match="timeout"):
        macos.dialog.choose_folder(timeout=timeout)
    assert fake_run.calls == []


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


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan"), 2 ** 29])
@pytest.mark.parametrize("show", [macos.dialog.alert, macos.dialog.confirm, macos.dialog.prompt])
def test_dialog_rejects_bad_timeout(fake_run, show, timeout):
    with pytest.raises(ValueError, match="timeout"):
        show("x", timeout=timeout)
    assert fake_run.calls == []


def test_dialog_prompt_keeps_trailing_newlines(fake_run):
    fake_run.stdout = "ok\nline 1\n\n"
    assert macos.dialog.prompt("x", default="line 1\n") == "line 1\n"
    fake_run.stdout = "ok\n\n"
    assert macos.dialog.prompt("x") == ""


def test_dialog_choose_an_empty_option(fake_run):
    fake_run.stdout = "ok\n\n"
    assert macos.dialog.choose(["", "Apple"], default="") == ""


def test_dialog_choose_matches_a_non_string_default(fake_run):
    fake_run.stdout = "ok\n2\n"
    assert macos.dialog.choose([1, 2, 3], default=2) == "2"  # type: ignore[list-item, arg-type]
    assert fake_run.args[-5:] == ["2", "", "1", "2", "3"]


def test_dialog_chosen_paths_may_hold_newlines(fake_run):
    fake_run.stdout = "ok\n/a/first\nline.pdf\0/b/ends with\n\0\n"
    assert macos.dialog.choose_files() == [Path("/a/first\nline.pdf"), Path("/b/ends with\n")]

    fake_run.stdout = "ok\n/a/odd\nname.pdf\0\n"
    assert macos.dialog.choose_file() == Path("/a/odd\nname.pdf")
    fake_run.stdout = "ok\n/Users/me/new\nfolder/\0\n"
    assert macos.dialog.choose_folder() == Path("/Users/me/new\nfolder")


def test_dialog_chosen_paths_keep_carriage_returns(fake_run, monkeypatch):
    import subprocess

    from macos import _system

    # Through the capture layer: the output comes back as bytes, decoded without
    # text mode, which would turn the \r\n and \r of these names into \n.
    calls = []

    def picker(args, **kwargs):
        calls.append(kwargs)
        stdout = "ok\n/a/first\r\nline.pdf\0/b/old\rmac.pdf\0\n".encode("utf-8")
        return subprocess.CompletedProcess(args, 0, stdout, b"")

    monkeypatch.setattr(_system.subprocess, "run", picker)
    assert macos.dialog.choose_files() == [Path("/a/first\r\nline.pdf"), Path("/b/old\rmac.pdf")]
    assert not calls[-1].get("text")


def test_run_decodes_exact_output_and_errors(fake_run, monkeypatch):
    import subprocess

    from macos import _system

    def tool(args, **kwargs):
        assert kwargs["input"] == "é\r\n".encode("utf-8") and "text" not in kwargs
        return subprocess.CompletedProcess(args, 1, b"", "falhou\r\n".encode("utf-8"))

    monkeypatch.setattr(_system.subprocess, "run", tool)
    with pytest.raises(macos.CommandError, match="falhou"):
        _system.run(["tool"], input="é\r\n", exact_newlines=True)


def test_dialog_refuses_a_string_for_options_and_types(fake_run):
    with pytest.raises(TypeError, match="options must be a list"):
        macos.dialog.choose("abc")  # would offer "a", "b" and "c"
    with pytest.raises(TypeError, match="types must be a list"):
        macos.dialog.choose_file(types="pdf")
    assert fake_run.calls == []


def test_dialog_confirm_checks_its_buttons(fake_run):
    for ok, cancel in (("", "Cancel"), ("OK", " "), ("Same", "Same")):
        with pytest.raises(ValueError, match="buttons"):
            macos.dialog.confirm("Sure?", ok=ok, cancel=cancel)
    assert fake_run.calls == []


def test_dialog_pickers_check_the_folder(fake_run, tmp_path):
    with pytest.raises(FileNotFoundError):
        macos.dialog.choose_file(folder=tmp_path / "nowhere")
    (tmp_path / "file.txt").write_text("")
    with pytest.raises(NotADirectoryError):
        macos.dialog.choose_folder(folder=tmp_path / "file.txt")
    fake_run.stdout = "ok\n{}\0\n".format(tmp_path)
    assert macos.dialog.choose_folder(folder=tmp_path) == tmp_path
    assert fake_run.args[-1] == str(tmp_path.resolve())


def test_dialog_says_why_osascript_refused(fake_run):
    fake_run.returncode, fake_run.stderr = 1, "execution error: No user interaction allowed. (-1713)"
    with pytest.raises(macos.MacOSError, match="no user session"):
        macos.dialog.alert("hi")
    fake_run.stderr = "execution error: Not authorized to send Apple events to System Events. (-1743)"
    with pytest.raises(macos.PermissionDeniedError, match="Automation"):
        macos.dialog.alert("hi")
    fake_run.stderr = "execution error: something else (-2741)"
    with pytest.raises(macos.CommandError):
        macos.dialog.alert("hi")


def test_a_warning_and_the_shown_line_in_one_write_keep_the_timeout(monkeypatch):
    # A real process, as select watches the pipe itself: both lines come in a single write, which a buffered
    # pipe would read at once, leaving the second where select can't see it.
    monkeypatch.setattr(_system.sys, "platform", "darwin")
    monkeypatch.setattr(macos.dialog, "_STARTING", 5.0)  # fails in seconds, not a minute, if the line isn't seen
    # exec: sleep is the process stopped at the deadline, as osascript is, with no child keeping the pipe open.
    both = "printf 'some warning\\npymacos: the dialog shows\\n' >&2; exec sleep 8"

    started = time.monotonic()
    assert macos.dialog._for_at_most(["sh", "-c", both], 1) is None
    assert time.monotonic() - started < 4


def test_an_answer_and_a_failure_come_back_whole_from_a_real_process(monkeypatch):
    monkeypatch.setattr(_system.sys, "platform", "darwin")
    shown = "printf 'pymacos: the dialog shows\\n' >&2; "

    assert macos.dialog._for_at_most(["sh", "-c", shown + "printf 'ok\\nPear\\n'"], 5) == "ok\nPear\n"
    with pytest.raises(macos.CommandError) as failed:
        macos.dialog._for_at_most(["sh", "-c", "printf 'w\\n' >&2; printf 'boom' >&2; exit 1"], 5)
    assert failed.value.stderr == "w\nboom"
