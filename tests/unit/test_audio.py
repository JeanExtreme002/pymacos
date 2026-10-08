"""Unit tests for :mod:`macos.audio`. They run on any platform."""

import pytest

import macos


def test_audio_device_matching():
    speakers = macos.audio.Device(1, "MacBook Pro Speakers", "BuiltInSpeakerDevice", "builtin", True, False)
    airpods = macos.audio.Device(2, "Alice's AirPods Pro", "AA-BB", "bluetooth", True, True)
    display = macos.audio.Device(3, "LG Display", "LG-1", "hdmi", True, False)
    devices = [speakers, airpods, display]
    find = macos.audio._find

    assert find("MacBook Pro Speakers", devices, "output") is speakers
    assert find("AA-BB", devices, "output") is airpods
    assert find("airpods", devices, "output") is airpods  # part of the name, any case
    assert find(display, devices, "output") is display
    with pytest.raises(ValueError, match="several"):
        find("p", devices, "output")
    with pytest.raises(ValueError, match="no output device"):
        find("Headphones", devices, "output")


class _FakeCoreAudio:
    """Input properties by (device, selector, element), as CoreAudio would hold them."""

    def __init__(self, values):
        import struct

        self.values = values
        self.pack = struct.pack
        self.writes = []

    def property(self, target, selector, scope=None, element=0):
        if selector == "slay":  # the stream configuration: one buffer with this many channels
            channels = self.values.get((target, "channels"), 0)
            return self.pack("II", 1, 0) + self.pack("IIQ", channels, 0, 0)
        value = self.values.get((target, selector, element))
        if value is None:
            return None
        return self.pack("f" if isinstance(value, float) else "I", value)

    def AudioObjectSetPropertyData(self, target, address, qualifier_size, qualifier, size, data):
        value = data._obj.value
        address = address._obj
        selector = address.selector.to_bytes(4, "big").decode()
        self.writes.append((target, selector, address.element, round(value, 3) if isinstance(value, float) else value))
        self.values[(target, selector, address.element)] = value
        return 0


@pytest.fixture
def fake_audio(monkeypatch):
    from macos import audio

    microphone = audio.Device(7, "USB Mic", "usb-mic", "usb", False, True)
    # Ten channels, each with its own volume: more than the 8 once assumed.
    values = {(7, "channels"): 10, (7, "mute", 0): 0}
    values.update({(7, "volm", channel): 0.5 if channel < 10 else 0.9 for channel in range(1, 11)})
    fake = _FakeCoreAudio(values)
    monkeypatch.setattr(audio, "_property", fake.property)
    monkeypatch.setattr(audio, "_core_audio", lambda: fake)
    monkeypatch.setattr(audio, "default_input", lambda: microphone)
    monkeypatch.setattr(audio, "inputs", lambda: [microphone])
    return fake


def test_input_volume_per_channel(fake_audio):
    # This microphone has no main volume, only one per channel.
    assert macos.audio.input_volume() == 0.54
    macos.audio.set_input_volume(0.25, device="USB")

    assert fake_audio.writes == [(7, "volm", channel, 0.25) for channel in range(1, 11)]
    assert macos.audio.input_volume() == 0.25


def test_mute_input(fake_audio):
    assert macos.audio.input_muted() is False
    macos.audio.mute_input()
    assert macos.audio.input_muted() is True
    macos.audio.mute_input(False)

    assert fake_audio.writes == [(7, "mute", 0, 1), (7, "mute", 0, 0)]

    del fake_audio.values[(7, "mute", 0)]
    with pytest.raises(macos.NotSupportedError, match="can't be muted"):
        macos.audio.mute_input()


def test_read_wav_handles_the_extensible_format():
    import struct

    samples = struct.pack("<4h", 1, -2, 3, -4)
    # WAVE_FORMAT_EXTENSIBLE (0xFFFE), with an odd-sized chunk before the data.
    fmt = struct.pack("<HHIIHH", 0xFFFE, 2, 22050, 22050 * 4, 4, 16) + b"\x00" * 24
    junk = b"LIST" + struct.pack("<I", 3) + b"abc\x00"
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + junk + b"data" + struct.pack("<I", len(samples)) + samples
    data = b"RIFF" + struct.pack("<I", len(body)) + body

    assert macos.audio._read_wav(data) == (2, 22050, samples)
    with pytest.raises(macos.MacOSError):
        macos.audio._read_wav(b"not a wav file at all")


def _wav(samples, channels, rate):
    """The bytes of a 16-bit WAV file holding ``samples``."""
    import array
    import io
    import sys
    import wave

    data = array.array("h", samples)
    if sys.byteorder == "big":
        data.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(2)
        writer.setframerate(rate)
        writer.writeframes(data.tobytes())
    return buffer.getvalue()


@pytest.fixture
def fake_pcm(monkeypatch):
    """Stands in for afconvert: decoding gives stereo samples, encoding records what was written."""
    import io
    from contextlib import contextmanager

    written = {}
    stereo = [100, -100, 200, -200, 300, -300, 400, -400, 500, -500]  # 5 frames at 10 frames a second

    @contextmanager
    def decoded(path, rate=None, channels=None):
        yield macos.audio._Samples(io.BytesIO(_wav(stereo, 2, 10)))

    @contextmanager
    def encoding_to(output, channels, rate, quality, lossless):
        pieces = []
        yield lambda samples: pieces.append(list(samples))
        written.update(samples=[value for piece in pieces for value in piece], channels=channels, rate=rate, pieces=pieces)

    monkeypatch.setattr(macos.audio, "_existing", lambda path: path)
    monkeypatch.setattr(macos.audio, "_decoded", decoded)
    monkeypatch.setattr(macos.audio, "_encoding_to", encoding_to)
    return written


def test_audio_sample_editing(fake_pcm):
    macos.audio.reverse("in.wav", "out.wav")
    assert fake_pcm["samples"] == [500, -500, 400, -400, 300, -300, 200, -200, 100, -100]  # channels stay in order

    macos.audio.trim("in.wav", "out.wav", 0.1, 0.2)
    assert fake_pcm["samples"] == [200, -200, 300, -300]

    macos.audio.gain("in.wav", "out.wav", 20)  # 10 times louder
    assert fake_pcm["samples"] == [1000, -1000, 2000, -2000, 3000, -3000, 4000, -4000, 5000, -5000]
    macos.audio.gain("in.wav", "out.wav", 60)  # clipped at the maximum
    assert max(fake_pcm["samples"]) == 32767 and min(fake_pcm["samples"]) == -32768

    macos.audio.fade("in.wav", "out.wav", fade_in=0.2, fade_out=0.2)
    assert fake_pcm["samples"] == [0, 0, 100, -100, 300, -300, 200, -200, 0, 0]

    macos.audio.concat(["a.wav", "b.wav"], "out.wav")
    assert len(fake_pcm["samples"]) == 20 and fake_pcm["channels"] == 2


def test_fade_goes_a_piece_at_a_time(fake_pcm, monkeypatch):
    monkeypatch.setattr(macos.audio, "_CHUNK_FRAMES", 2)
    # The same samples as in one piece, with fades that cross the pieces' edges and overlap.
    macos.audio.fade("in.wav", "out.wav", fade_in=0.2, fade_out=0.2)
    assert fake_pcm["pieces"] == [[0, 0, 100, -100], [300, -300, 200, -200], [0, 0]]
    macos.audio.fade("in.wav", "out.wav", fade_in=0.5, fade_out=0.5)
    assert fake_pcm["samples"] == [0, 0, 24, -24, 48, -48, 48, -48, 0, 0]  # as when it was done whole


def test_trim_and_gain_go_a_piece_at_a_time(fake_pcm, monkeypatch):
    monkeypatch.setattr(macos.audio, "_CHUNK_FRAMES", 2)
    macos.audio.trim("in.wav", "out.wav", 0.1)
    assert fake_pcm["pieces"] == [[200, -200, 300, -300], [400, -400, 500, -500]]  # frames 1 to 4, two at a time
    macos.audio.gain("in.wav", "out.wav", -20)  # 10 times quieter
    assert fake_pcm["pieces"] == [[10, -10, 20, -20], [30, -30, 40, -40], [50, -50]]
    with pytest.raises(ValueError, match="past the end"):
        macos.audio.trim("in.wav", "out.wav", 0.5)


def test_gain_table_matches_multiplying_each_sample():
    for decibels in (-60, -6, 0.5, 6, 20):
        factor = 10 ** (decibels / 20)
        table = macos.audio._gain_table(factor)
        for value in (-32768, -32767, -12345, -1, 0, 1, 777, 32767):
            assert table[value] == macos.audio._clip(value * factor)


def test_wav_samples_are_read_in_whole_frames():
    import io

    samples = macos.audio._Samples(io.BytesIO(_wav([1, -1, 2, -2, 3, -3], 2, 8000)))
    assert (samples.channels, samples.rate, samples.frames) == (2, 8000, 3)
    assert list(samples.read(2)) == [1, -1, 2, -2]
    assert list(samples.read(5)) == [3, -3]  # what's left
    samples.seek(1)
    assert list(samples.read(1)) == [2, -2]


def test_wav_samples_stop_at_the_end_of_the_data_chunk():
    import io
    import struct

    # A LIST chunk (metadata) after the samples, as some tools write it: never read as sound.
    listed = struct.pack("<4sI4s4sI", b"LIST", 14, b"INFO", b"ISFT", 5) + b"tool\x00\x00"
    wav = _wav([1, -1, 2, -2], 2, 8000) + listed
    wav = wav[:4] + struct.pack("<I", len(wav) - 8) + wav[8:]  # RIFF size, including the new chunk

    samples = macos.audio._Samples(io.BytesIO(wav))
    assert samples.frames == 2
    assert list(samples.read(10)) == [1, -1, 2, -2]  # an oversized read stops at the data's end
    assert list(samples.read(10)) == []  # and nothing comes after it
    samples.seek(1)
    assert list(samples.read(10)) == [2, -2]


def test_record_until_silence_stops_after_quiet(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from macos import _capture

    clock = [0.0]
    calls = []

    def send(receiver, selector, *args, **kwargs):
        calls.append(selector)
        if selector == "averagePowerForChannel:":
            # Quiet, then speech from 0.5 s to 1.5 s, then quiet again (in decibels).
            return -10.0 if 0.5 <= clock[0] < 1.5 else -60.0
        return True

    target = tmp_path / "note.m4a"
    monkeypatch.setattr(_capture, "require_permission", lambda media: None)
    monkeypatch.setattr(macos.audio, "_recorder", lambda path, channels, metering=False: path.write_bytes(b"x") or 1)
    monkeypatch.setattr(macos.audio._objc, "send", send)
    monkeypatch.setattr(macos.audio._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(macos.audio.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(macos.audio.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))

    macos.audio.record_until_silence(target, max_seconds=30, silence=1.0)

    assert 2.4 <= clock[0] <= 2.7  # about 1 s after the speech ended, not at 30 s
    assert calls[-1] == "stop"
    assert target.read_bytes() == b"x"


def test_a_failed_recording_leaves_the_old_file_alone(monkeypatch, tmp_path):
    from contextlib import nullcontext

    from macos import _capture

    target = tmp_path / "memo.m4a"
    target.write_bytes(b"yesterday")
    # prepareToRecord empties the file it's given: it must never be the target itself.
    monkeypatch.setattr(_capture, "require_permission", lambda media: None)
    monkeypatch.setattr(macos.audio, "_recorder", lambda path, channels, metering=False: path.write_bytes(b"") or 1)
    monkeypatch.setattr(macos.audio._objc, "send", lambda receiver, selector, *args, **kwargs: selector != "record")
    monkeypatch.setattr(macos.audio._objc, "autorelease_pool", nullcontext)

    with pytest.raises(macos.MacOSError, match="could not start"):
        macos.audio.record(target, 1)
    assert target.read_bytes() == b"yesterday"
    assert [path.name for path in tmp_path.iterdir()] == ["memo.m4a"]


@pytest.mark.parametrize("record", ["record", "record_until_silence"])
def test_a_recording_stopped_with_ctrl_c_is_kept(monkeypatch, tmp_path, record):
    from contextlib import nullcontext

    from macos import _capture

    def interrupt(seconds):
        raise KeyboardInterrupt

    target = tmp_path / "memo.m4a"
    target.write_bytes(b"yesterday")
    monkeypatch.setattr(_capture, "require_permission", lambda media: None)
    monkeypatch.setattr(macos.audio, "_recorder", lambda path, channels, metering=False: path.write_bytes(b"so far") or 1)
    monkeypatch.setattr(macos.audio._objc, "send", lambda receiver, selector, *args, **kwargs: True)
    monkeypatch.setattr(macos.audio._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(macos.audio.time, "sleep", interrupt)

    with pytest.raises(KeyboardInterrupt):  # the script still stops, as asked
        getattr(macos.audio, record)(target, 60)
    assert target.read_bytes() == b"so far"  # with what was recorded until then
    assert [path.name for path in tmp_path.iterdir()] == ["memo.m4a"]


@pytest.mark.parametrize("record", ["record", "record_until_silence"])
def test_ctrl_c_before_anything_was_saved_stays_a_ctrl_c(monkeypatch, tmp_path, record):
    from contextlib import nullcontext

    from macos import _capture

    def interrupt(seconds):
        raise KeyboardInterrupt

    target = tmp_path / "memo.m4a"
    target.write_bytes(b"yesterday")
    monkeypatch.setattr(_capture, "require_permission", lambda media: None)
    monkeypatch.setattr(macos.audio, "_recorder", lambda path, channels, metering=False: 1)  # writes nothing
    monkeypatch.setattr(macos.audio._objc, "send", lambda receiver, selector, *args, **kwargs: True)
    monkeypatch.setattr(macos.audio._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(macos.audio.time, "sleep", interrupt)

    with pytest.raises(KeyboardInterrupt):  # not a MacOSError: the user stopped it
        getattr(macos.audio, record)(target, 60)
    assert target.read_bytes() == b"yesterday"


@pytest.mark.parametrize("record", ["record", "record_until_silence"])
def test_ctrl_c_before_any_sound_keeps_the_old_file(monkeypatch, tmp_path, record):
    from contextlib import nullcontext

    from macos import _capture

    def interrupt(seconds):
        raise KeyboardInterrupt

    def send(receiver, selector, *args, **kwargs):
        return 0.0 if selector == "currentTime" else True  # prepared, but no sound captured yet

    target = tmp_path / "memo.m4a"
    target.write_bytes(b"yesterday")
    monkeypatch.setattr(_capture, "require_permission", lambda media: None)
    # prepareToRecord already wrote the file's header.
    monkeypatch.setattr(macos.audio, "_recorder", lambda path, channels, metering=False: path.write_bytes(b"header") or 1)
    monkeypatch.setattr(macos.audio._objc, "send", send)
    monkeypatch.setattr(macos.audio._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(macos.audio.time, "sleep", interrupt)

    with pytest.raises(KeyboardInterrupt):
        getattr(macos.audio, record)(target, 60)
    assert target.read_bytes() == b"yesterday"  # not replaced by an empty recording
    assert [path.name for path in tmp_path.iterdir()] == ["memo.m4a"]


@pytest.mark.parametrize("record", ["record", "record_until_silence"])
def test_a_recording_that_captured_no_sound_is_a_failure(monkeypatch, tmp_path, record):
    from contextlib import nullcontext

    from macos import _capture

    def send(receiver, selector, *args, **kwargs):
        return 0.0 if selector == "currentTime" else (-60.0 if selector == "averagePowerForChannel:" else True)

    target = tmp_path / "memo.m4a"
    target.write_bytes(b"yesterday")
    monkeypatch.setattr(_capture, "require_permission", lambda media: None)
    monkeypatch.setattr(macos.audio, "_recorder", lambda path, channels, metering=False: path.write_bytes(b"header") or 1)
    monkeypatch.setattr(macos.audio._objc, "send", send)
    monkeypatch.setattr(macos.audio._objc, "autorelease_pool", nullcontext)
    monkeypatch.setattr(macos.audio.time, "sleep", lambda seconds: None)

    with pytest.raises(macos.MacOSError, match="wasn't saved"):  # ran its course, but recorded nothing
        getattr(macos.audio, record)(target, 1)
    assert target.read_bytes() == b"yesterday"


def test_audio_argument_checks(tmp_path):
    with pytest.raises(ValueError, match="0.0 to 1.0"):
        macos.audio.set_input_volume(1.5)
    with pytest.raises(ValueError, match="positive"):
        macos.audio.record(tmp_path / "out.m4a", 0)
    with pytest.raises(ValueError, match="channels"):
        macos.audio.record(tmp_path / "out.m4a", 1, channels=3)
    with pytest.raises(ValueError, match="can't record '.mp3'"):
        macos.audio.record(tmp_path / "out.mp3", 1)
    with pytest.raises(ValueError, match="positive"):
        macos.audio.input_level(0)
    with pytest.raises(ValueError, match="can't write '.mp3'"):
        macos.audio.convert(__file__, tmp_path / "out.mp3")
    with pytest.raises(ValueError, match="lossless"):
        macos.audio.convert(__file__, tmp_path / "out.wav", lossless=True)
    with pytest.raises(ValueError, match="quality"):
        macos.audio.convert(__file__, tmp_path / "out.m4a", quality="best")
    with pytest.raises(ValueError, match="negative"):
        macos.audio.trim(__file__, tmp_path / "out.m4a", -1)
    with pytest.raises(ValueError, match="at least one"):
        macos.audio.concat([], tmp_path / "out.m4a")
    with pytest.raises(ValueError, match="negative"):
        macos.audio.fade(__file__, tmp_path / "out.m4a", fade_in=-1)
    with pytest.raises(ValueError, match="positive"):
        macos.audio.speed(__file__, tmp_path / "out.m4a", 0)
    with pytest.raises(ValueError, match="limit"):
        macos.audio.classify(__file__, limit=0)
    with pytest.raises(ValueError, match="threshold"):
        macos.audio.record_until_silence(tmp_path / "out.m4a", threshold=2)
    with pytest.raises(ValueError, match="can't record"):
        macos.audio.record_until_silence(tmp_path / "out.mp3")
