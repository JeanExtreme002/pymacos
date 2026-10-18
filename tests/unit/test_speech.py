"""Unit tests for :mod:`macos.speech`. They run on any platform."""

import pytest

import macos


def test_say_reads_text_from_stdin(fake_run):
    macos.say("-not an option", voice="Luciana", rate=180)

    assert fake_run.args == ["say", "-v", "Luciana", "-r", "180", "-f", "-"]
    assert fake_run.calls[-1]["input"] == "-not an option"


def test_voices_parses_names_with_spaces(fake_run):
    fake_run.stdout = (
        "Albert              en_US    # Hello! My name is Albert.\n"
        "Eddy (English (US)) en_US    # Hello! My name is Eddy.\n"
        "Luciana             pt_BR    # Olá, meu nome é Luciana.\n"
    )

    voices = macos.speech.voices()

    assert [v.name for v in voices] == ["Albert", "Eddy (English (US))", "Luciana"]
    assert voices[2].locale == "pt_BR"
    assert voices[2].sample == "Olá, meu nome é Luciana."


def test_say_without_waiting_reaps_the_process(fake_run, monkeypatch):
    started = []

    class FakeStdin:
        def __init__(self):
            self.data, self.closed = b"", False

        def write(self, data):
            self.data += data

        def close(self):
            self.closed = True

    class FakePopen:
        def __init__(self, args, **kwargs):
            self.args = args
            self.stdin = FakeStdin()
            self.waited = False
            started.append(self)

        def wait(self):
            self.waited = True

    monkeypatch.setattr(macos.speech.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(macos.speech.threading, "Thread", _ImmediateThread)

    macos.say("-hi", wait=False)

    process = started[0]
    assert process.args == ["say", "-f", "-"]
    # The text is written and stdin closed before say() returns.
    assert process.stdin.data == b"-hi" and process.stdin.closed
    assert process.waited


def test_say_without_waiting_reports_a_missing_command(fake_run, monkeypatch):
    def missing(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(macos.speech.subprocess, "Popen", missing)

    with pytest.raises(macos.NotSupportedError):
        macos.say("x", wait=False)


class _ImmediateThread:
    def __init__(self, target, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


def test_say_to_a_file(fake_run, tmp_path):
    target = macos.say("hi", output=tmp_path / "speech.WAV", wait=False)

    assert target == (tmp_path / "speech.WAV").resolve()
    assert fake_run.args == ["say", "-o", str(target), "--data-format=LEI16", "-f", "-"]


def test_say_rejects_unknown_audio_formats(fake_run, tmp_path):
    with pytest.raises(ValueError, match="unsupported audio format"):
        macos.say("hi", output=tmp_path / "speech.mp3")


def _fake_popen(monkeypatch, fail_write=None):
    started = []

    class FakeStdin:
        def __init__(self):
            self.data, self.closed = b"", False

        def write(self, data):
            if fail_write is not None:
                raise fail_write
            self.data += data

        def close(self):
            self.closed = True

    class FakePopen:
        def __init__(self, args, **kwargs):
            self.args, self.stdin = args, FakeStdin()
            self.killed = self.waited = False
            started.append(self)

        def kill(self):
            self.killed = True

        def wait(self):
            self.waited = True

    monkeypatch.setattr(macos.speech.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(macos.speech.threading, "Thread", _ImmediateThread)
    return started


def test_say_without_waiting_replaces_unencodable_text(fake_run, monkeypatch):
    # A file name decoded with surrogateescape: the blocking path speaks it
    # with errors replaced, and so must this one.
    started = _fake_popen(monkeypatch)

    macos.say("caf\udce9", wait=False)

    assert started[0].stdin.data == b"caf?" and started[0].stdin.closed


def test_say_without_waiting_kills_say_when_interrupted(fake_run, monkeypatch):
    started = _fake_popen(monkeypatch, fail_write=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        macos.say("hi", wait=False)

    process = started[0]
    assert process.stdin.closed and process.killed and process.waited


@pytest.mark.parametrize("wait", [True, False])
@pytest.mark.parametrize("text", [None, b"hi", 5])
def test_say_rejects_text_that_is_not_a_str(fake_run, monkeypatch, text, wait):
    # With None, say would otherwise read the caller's own stdin.
    started = _fake_popen(monkeypatch)

    with pytest.raises(TypeError, match="text must be a str"):
        macos.say(text, wait=wait)

    assert not fake_run.calls and not started


@pytest.mark.parametrize("output", [None, "speech.aiff"])
def test_say_rejects_the_voice_listing_sentinel(fake_run, monkeypatch, tmp_path, output):
    # "say -v ?" lists the voices and exits 0, speaking or saving nothing.
    started = _fake_popen(monkeypatch)

    with pytest.raises(ValueError, match="voices"):
        macos.say("hi", voice="?", output=output and tmp_path / output)
    with pytest.raises(ValueError, match="voices"):
        macos.say("hi", voice="?", wait=False)

    assert not fake_run.calls and not started


@pytest.mark.parametrize(
    "rate, error", [(True, TypeError), ("180", TypeError), (0, ValueError), (-5, ValueError), (float("nan"), ValueError)]
)
def test_say_rejects_rates_say_would_ignore(fake_run, rate, error):
    with pytest.raises(error, match="rate must be"):
        macos.say("hi", rate=rate)

    assert not fake_run.calls


def test_say_accepts_a_fractional_rate(fake_run):
    macos.say("hi", rate=180.5)

    assert fake_run.args == ["say", "-r", "180.5", "-f", "-"]
