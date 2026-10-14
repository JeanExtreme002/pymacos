"""Fixtures shared by the live tests, and the switch that makes a missing permission fail them."""

import os
import re
import time
import uuid
from pathlib import Path

import pytest

import macos

# The reasons the live tests give when this Mac lacks a privacy permission ("no Accessibility
# permission", "needs the Input Monitoring and Accessibility permissions"). The opt-in switches'
# reasons ("...: set PYMACOS_BROWSER_TESTS=1 to run") don't match.
_PERMISSION_SKIP = re.compile(r"\b(?:no|needs the) [\w ]*permissions?\b")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """
    With ``PYMACOS_REQUIRE_PERMISSIONS=1``, a test skipped for a missing permission fails instead.

    For CI, whose runners have the permissions granted: a runner image that loses them would
    otherwise turn a fifth of the live suite into skips, and the run would stay green.
    """
    outcome = yield
    report = outcome.get_result()
    if not (report.skipped and os.environ.get("PYMACOS_REQUIRE_PERMISSIONS")) or hasattr(report, "wasxfail"):
        return
    reason = report.longrepr[2] if isinstance(report.longrepr, tuple) else str(report.longrepr)
    if _PERMISSION_SKIP.search(reason):
        report.outcome = "failed"
        report.longrepr = "PYMACOS_REQUIRE_PERMISSIONS is set, and this Mac lacks a permission: {}".format(reason)


@pytest.fixture
def speech(tmp_path):
    """
    A few seconds of speech, made by ``say``, or of a warbling tone when ``say`` fails.

    On CI runners, say now and then writes files of a few milliseconds, even
    several times in a row (afinfo, independent of pymacos, agrees), and once
    wrote one of the right length in which the sound classifier heard nothing:
    a file is kept only when it's long enough and mostly sound, not silence.
    The tone keeps the editing tests running; only the speech classifier needs
    real speech, and checks the file's name.
    """
    import math
    import re
    import subprocess
    import wave

    path = tmp_path / "speech.aiff"
    for attempt in range(3):
        time.sleep(attempt)
        subprocess.run(["say", "-o", str(path), "Good morning everyone, today we talk about the ocean."], check=True)
        details = subprocess.run(["afinfo", str(path)], capture_output=True, text=True, check=True).stdout
        found = re.search(r"estimated duration: ([0-9.]+)", details)
        if found and float(found.group(1)) > 2 and _mostly_sound(path):
            return path
    rate, seconds = 22050, 2.6
    samples = bytearray()
    for index in range(int(rate * seconds)):
        moment = index / rate
        pitch = 220 + 80 * math.sin(2 * math.pi * 3 * moment)
        level = 0.3 + 0.2 * math.sin(2 * math.pi * 2 * moment)
        samples += int(32767 * level * math.sin(2 * math.pi * pitch * moment)).to_bytes(2, "little", signed=True)
    raw = tmp_path / "tone.wav"
    with wave.open(str(raw), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(samples))
    tone = tmp_path / "tone.aiff"
    subprocess.run(["afconvert", "-f", "AIFF", "-d", "BEI16", str(raw), str(tone)], check=True)
    return tone


def _mostly_sound(path):
    """
    Whether most of ``path`` is sound: over half its 50 ms windows louder than -36 dBFS.

    Read by afconvert and the wave module, independent of pymacos. Speech from say
    is about 95% sound (the gaps between words are the rest); a silent file is 0%.
    """
    import array
    import math
    import subprocess
    import sys
    import wave

    pcm = path.with_name(path.stem + "-check.wav")
    subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16", str(path), str(pcm)], check=True)
    with wave.open(str(pcm)) as audio:
        step = int(audio.getframerate() * 0.05) * audio.getnchannels()
        samples = array.array("h", audio.readframes(audio.getnframes()))
    pcm.unlink()
    if sys.byteorder == "big":
        samples.byteswap()  # the WAV holds little-endian samples
    windows = [samples[start:start + step] for start in range(0, len(samples) - step + 1, step)] if step else []
    loud = sum(1 for window in windows if math.sqrt(sum(value * value for value in window) / len(window)) > 500)
    return bool(windows) and loud > len(windows) / 2


@pytest.fixture
def test_window():
    """A window of our own, in a helper process, to move around without touching the user's."""
    import subprocess
    import sys

    if not macos.windows.has_permission():
        pytest.skip("no Accessibility permission")
    front = macos.windows.focused()
    title = "pymacos test {}".format(uuid.uuid4().hex[:8])
    helper = Path(__file__).with_name("_window_app.py")
    process = subprocess.Popen([sys.executable, str(helper), title, "20"], stdout=subprocess.PIPE, text=True)
    try:
        process.stdout.readline()
        app = next(app for app in macos.apps.running(include_background=True) if app.pid == process.pid)
        for _ in range(20):
            found = macos.windows.list(app, title=title)
            if found:
                break
            time.sleep(0.1)
        yield found[0]
    finally:
        process.kill()
        process.wait()
        if front is not None:
            try:
                front.focus()  # give the focus back
            except macos.MacOSError:
                pass
