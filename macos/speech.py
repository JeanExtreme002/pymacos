# -*- coding: utf-8 -*-

"""
Text to speech with the system voices.

::

    macos.say("Hello from Python")
    macos.say("Hello!", voice="Samantha", rate=180)
    [voice.name for voice in macos.speech.voices()]
"""

import os
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Union

from ._system import popen, run as _run

__all__ = ["say", "voices", "Voice"]

_VOICES_TIMEOUT = 30.0  # seconds for ``say -v ?``: it lists the voices at once, unless speech is wedged


@dataclass(frozen=True)
class Voice:
    """An installed speech voice."""

    name: str
    locale: str
    sample: str


# `say -o` picks the file format from the extension; WAV also needs a sample
# format, since its default one isn't valid for WAV.
_AUDIO_FORMATS = {".aiff": [], ".aif": [], ".m4a": [], ".caf": [], ".wav": ["--data-format=LEI16"]}


def say(
    text: str,
    *,
    voice: Optional[str] = None,
    rate: Optional[float] = None,
    wait: bool = True,
    output: Union[str, "os.PathLike[str]", None] = None,
) -> Optional[Path]:
    """
    Speak ``text`` out loud, or save the speech to an audio file.

    ``voice`` is a voice name from :func:`~macos.speech.voices` (the system default when
    omitted) and ``rate`` is the speed in words per minute (about 175–200 is
    normal). With ``wait=False`` this returns immediately while speech plays.

    With ``output``, nothing is played: the speech is written to that file
    (``.aiff``, ``.m4a``, ``.wav`` or ``.caf``) and its path is returned.

    An unknown ``voice`` is not an error: ``say`` falls back to the default
    voice, matching names loosely (``"samantha"`` and ``"Eddy"`` both work).
    ``voice="?"`` is a ``ValueError``: ``say`` would list the voices instead of
    speaking; use :func:`~macos.speech.voices` for that. A ``rate`` that isn't a
    positive number is an error too, since ``say`` would silently ignore it.
    """
    # Always hand say a str: with input=None it would read the caller's own
    # stdin, since the text is read from "-".
    if not isinstance(text, str):
        raise TypeError("text must be a str, not {}".format(type(text).__name__))
    args = ["say"]
    if voice is not None:
        if voice == "?":
            raise ValueError("voice '?' lists the voices instead of speaking; use macos.speech.voices()")
        args += ["-v", voice]
    if rate is not None:
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            raise TypeError("rate must be a number of words per minute, not {!r}".format(rate))
        if not rate > 0:
            raise ValueError("rate must be positive, not {}".format(rate))
        args += ["-r", str(rate)]
    target = None
    if output is not None:
        target = Path(output).expanduser().resolve()
        if target.suffix.lower() not in _AUDIO_FORMATS:
            raise ValueError(
                "unsupported audio format {!r}; use one of {}".format(target.suffix, ", ".join(sorted(_AUDIO_FORMATS)))
            )
        args += ["-o", str(target), *_AUDIO_FORMATS[target.suffix.lower()]]
    # Read the text from stdin rather than argv, so text starting with "-"
    # isn't taken for an option.
    args += ["-f", "-"]

    if wait or target is not None:
        _run(args, input=text)
        return target

    # Encode before starting say, the way the blocking path does (errors
    # replaced), so a failure here can't leave a process waiting on stdin.
    data = text.encode("utf-8", "replace")
    process = popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Write the text before returning, not from a background thread: if the
    # script ends right after this call, a thread could be killed before the
    # text reached say, which would then speak nothing.
    assert process.stdin is not None
    try:
        process.stdin.write(data)
        process.stdin.close()
    except BrokenPipeError:
        pass  # say exited early; there is nothing left to speak to.
    except BaseException:
        # Interrupted mid-write (Ctrl-C, say): don't leave say behind.
        try:
            process.stdin.close()
        except OSError:
            pass
        process.kill()
        process.wait()
        raise

    # Reap the process when it finishes, so no zombie is left behind.
    threading.Thread(target=process.wait, daemon=True).start()
    return None


def voices() -> List[Voice]:
    """Return the voices installed on this Mac."""
    found = []
    for line in _run(["say", "-v", "?"], timeout=_VOICES_TIMEOUT).splitlines():
        # Format: "<name, may contain spaces> <locale>    # <sample sentence>"
        head, _, sample = line.partition("#")
        parts = head.split()
        if len(parts) >= 2:
            found.append(Voice(name=" ".join(parts[:-1]), locale=parts[-1], sample=sample.strip()))
    return found
