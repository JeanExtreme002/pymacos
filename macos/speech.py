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

from ._system import executable, require_macos, run as _run
from .errors import NotSupportedError

__all__ = ["say", "voices", "Voice"]


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
    rate: Optional[int] = None,
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
    """
    args = ["say"]
    if voice is not None:
        args += ["-v", voice]
    if rate is not None:
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

    require_macos()
    try:
        process = subprocess.Popen(
            args, executable=executable(args[0]), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    except FileNotFoundError:
        raise NotSupportedError("the 'say' command was not found on this system") from None

    # Write the text before returning, not from a background thread: if the
    # script ends right after this call, a thread could be killed before the
    # text reached say, which would then speak nothing.
    assert process.stdin is not None
    try:
        process.stdin.write(text.encode("utf-8"))
        process.stdin.close()
    except BrokenPipeError:
        pass  # say exited early; there is nothing left to speak to.

    # Reap the process when it finishes, so no zombie is left behind.
    threading.Thread(target=process.wait, daemon=True).start()
    return None


def voices() -> List[Voice]:
    """Return the voices installed on this Mac."""
    found = []
    for line in _run(["say", "-v", "?"], timeout=30).splitlines():  # it lists them at once, unless speech is wedged
        # Format: "<name, may contain spaces> <locale>    # <sample sentence>"
        head, _, sample = line.partition("#")
        parts = head.split()
        if len(parts) >= 2:
            found.append(Voice(name=" ".join(parts[:-1]), locale=parts[-1], sample=sample.strip()))
    return found
