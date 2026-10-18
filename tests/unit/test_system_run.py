"""The internal command runners of ``macos._system``: what they hand the command, and how they stop it."""

import os
import signal
import subprocess

import pytest

from macos import _system


class _FakeProcess:
    """``subprocess.Popen`` for a command that runs until ``communicate`` plays what happens meanwhile."""

    def __init__(self, during=None):
        self.during = during
        self.options = {}
        self.signals = []
        self.calls = []
        self.returncode = None

    def __call__(self, args, **options):
        self.options = options
        return self

    def communicate(self, timeout=None):
        self.calls.append(timeout)
        if len(self.calls) == 1 and self.during is not None:
            self.during(self)
        self.returncode = 0
        return None, b""

    def poll(self):
        return self.returncode

    def send_signal(self, number):
        self.signals.append(number)

    def kill(self):
        self.signals.append("kill")


@pytest.fixture
def popen(monkeypatch):
    monkeypatch.setattr(_system.sys, "platform", "darwin")

    def install(during=None):
        process = _FakeProcess(during)
        monkeypatch.setattr(_system.subprocess, "Popen", process)
        return process

    return install


def test_the_command_runs_in_a_process_group_of_its_own(popen):
    process = popen()
    _system.run_to_the_end(["screencapture", "-v", "x.mov"], timeout=10, grace=5)
    # No SIGINT sent to Python's group (a terminal's Ctrl-C, Jupyter's interrupt) reaches it by itself.
    assert process.options.get("process_group") == 0 or process.options.get("start_new_session") is True


def test_an_interrupt_is_passed_on_exactly_once_wherever_it_came_from(popen):
    def interrupted(process):
        raise KeyboardInterrupt

    process = popen(interrupted)
    with pytest.raises(KeyboardInterrupt):
        _system.run_to_the_end(["screencapture", "-v", "x.mov"], timeout=10, grace=5)
    # Asked to stop once, then waited for to finish its file, never killed.
    assert process.signals == [signal.SIGINT] and process.calls == [10, 5]


def test_a_signal_that_ends_python_is_passed_on_to_the_command_first(popen, monkeypatch):
    killed = []
    monkeypatch.setattr(_system.os, "kill", lambda pid, number: killed.append((pid, number)))

    def terminated(process):
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)  # passed on while it runs
        handler(signal.SIGTERM, None)

    process = popen(terminated)
    _system.run_to_the_end(["screencapture", "-v", "x.mov"], timeout=10, grace=5)
    assert process.signals == [signal.SIGTERM]  # the command stops, as it did in Python's group
    assert killed == [(os.getpid(), signal.SIGTERM)]  # then Python ends as it would have
    assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL  # and nothing is left behind


def test_a_signal_python_handles_itself_is_left_alone(popen):
    def own(number, frame):
        pass

    seen = []
    previous = signal.signal(signal.SIGHUP, own)
    try:
        popen(lambda process: seen.append(signal.getsignal(signal.SIGHUP)))
        _system.run_to_the_end(["screencapture", "-v", "x.mov"], timeout=10, grace=5)
        assert seen == [own] and signal.getsignal(signal.SIGHUP) is own
    finally:
        signal.signal(signal.SIGHUP, previous)


def test_input_that_utf_8_cannot_hold_raises_in_either_mode(fake_run):
    for exact_newlines in (False, True):
        with pytest.raises(UnicodeEncodeError):
            _system.run(["say"], input="a\udcffb", exact_newlines=exact_newlines)
    assert fake_run.calls == []  # never sent with "?" in its place

    _system.run(["say"], input="olá")
    assert fake_run.calls[-1]["input"] == "olá"


def test_a_command_without_input_never_reads_python_s_own(fake_run):
    for run in (lambda: _system.run(["pbpaste"]), lambda: _system.run(["pbpaste"], exact_newlines=True),
                lambda: _system.run_bytes(["pbpaste"])):
        run()
        assert fake_run.calls[-1]["stdin"] is subprocess.DEVNULL and fake_run.calls[-1]["input"] is None

    _system.run(["pbcopy"], input="x")
    assert "stdin" not in fake_run.calls[-1]  # input and stdin together: subprocess.run refuses them


def test_a_stuck_command_is_killed(popen):
    def stuck(process):
        raise subprocess.TimeoutExpired("screencapture", 10)

    process = popen(stuck)
    with pytest.raises(_system.CommandTimeoutError):
        _system.run_to_the_end(["screencapture", "-v", "x.mov"], timeout=10, grace=5)
    assert process.signals == ["kill"]


def test_the_command_never_reads_the_terminal_and_its_input_stays_open_until_it_ends(popen, monkeypatch):
    def running(process):
        stdin = process.options["stdin"]
        os.set_blocking(stdin, False)
        with pytest.raises(BlockingIOError):  # open and empty: neither a key nor an EOF to read
            os.read(stdin, 1)

    process = popen(running)
    close = os.close
    # The parent's copy of the read end stays open here, standing in for the command's own.
    monkeypatch.setattr(_system.os, "close", lambda fd: None if fd == process.options.get("stdin") else close(fd))
    _system.run_to_the_end(["screencapture", "-v", "x.mov"], timeout=10, grace=5)
    monkeypatch.undo()
    stdin = process.options["stdin"]
    try:
        assert os.read(stdin, 1) == b""  # the write end was closed once it had ended
    finally:
        close(stdin)
