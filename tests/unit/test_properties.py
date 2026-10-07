"""
Property-based tests of the package's pure helpers: the rules that must hold for any input,
not just the examples in the other files. They run on any platform.
"""

import math
import re

import pytest

from macos import pdf, windows

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import assume, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


# --- windows._grid ----------------------------------------------------------------

# NSScreen hands over points that may be fractional (the Dock's size is), so the areas are too.
areas = st.tuples(
    st.integers(-3000, 3000) | st.integers(-6000, 6000).map(lambda half: half / 2),
    st.integers(-3000, 3000) | st.integers(-6000, 6000).map(lambda half: half / 2),
    st.integers(200, 6000) | st.integers(400, 12000).map(lambda half: half / 2),
    st.integers(200, 4000) | st.integers(400, 8000).map(lambda half: half / 2),
)


@given(count=st.integers(0, 40), area=areas, columns=st.one_of(st.none(), st.integers(1, 12)), gap=st.integers(0, 20))
def test_grid_gives_each_window_its_own_room_inside_the_area(count, area, columns, gap):
    try:
        frames = windows._grid(count, area, columns, gap)
    except ValueError:
        return  # no room for that many windows with that gap: refused, never squeezed
    assert len(frames) == count
    x, y, width, height = area
    for left, top, frame_width, frame_height in frames:
        assert frame_width >= 1 and frame_height >= 1
        # Within the area, give or take the half point that rounding to whole points may cost.
        assert x - 0.5 <= left and left + frame_width <= x + width + 0.5
        assert y - 0.5 <= top and top + frame_height <= y + height + 0.5
    for index, (left, top, frame_width, frame_height) in enumerate(frames):
        for other_left, other_top, other_width, other_height in frames[index + 1:]:
            apart = (
                left + frame_width <= other_left
                or other_left + other_width <= left
                or top + frame_height <= other_top
                or other_top + other_height <= top
            )
            assert apart, "two windows overlap"


@given(count=st.integers(1, 40), area=areas, columns=st.one_of(st.none(), st.integers(1, 12)))
def test_grid_without_gaps_covers_the_whole_area(count, area, columns):
    try:
        frames = windows._grid(count, area, columns, 0)
    except ValueError:
        return
    x, y, width, height = area

    def edge(value):
        return math.floor(value + 0.5)  # half points round up, as the grid rounds them

    covered = (edge(x + width) - edge(x)) * (edge(y + height) - edge(y))  # its edges, rounded once
    assert sum(frame_width * frame_height for _, _, frame_width, frame_height in frames) == covered


# --- pdf redaction ----------------------------------------------------------------

words = st.text(alphabet=st.characters(categories=("L", "N")), min_size=1, max_size=8)


@given(text=st.text(max_size=200))
def test_utf16_offsets_count_as_utf16_does(text):
    offsets = pdf._utf16_offsets(text)
    assert len(offsets) == len(text) + 1
    assert offsets[-1] == len(text.encode("utf-16-le")) // 2
    for index, character in enumerate(text):
        assert offsets[index + 1] - offsets[index] == len(character.encode("utf-16-le")) // 2


@settings(max_examples=200)
@given(target=st.lists(words, min_size=1, max_size=3).map(" ".join), filler=st.lists(words, max_size=10))
def test_scrub_leaves_no_trace_of_a_target_and_keeps_the_rest(target, filler):
    # Upper case only where it is a case change of the same letters ("ŉ" becomes the two "ʼN").
    assume(len(target.upper()) == len(target) and target.upper().lower() == target.lower())
    text = " ".join(filler[: len(filler) // 2] + [target.upper()] + filler[len(filler) // 2:])
    patterns = pdf._patterns(target)
    counts = [0]
    scrubbed = pdf._scrub(text, patterns, counts)

    assert len(scrubbed) == len(text)
    assert counts[0] >= 1
    assert not patterns[0][1].search(scrubbed)  # nothing left to find
    for original, kept in zip(text, scrubbed):
        assert kept in (original, pdf._BLOCK)  # only blocked out, never rewritten


@given(target=words, before=words, after=words)
def test_a_target_never_matches_inside_a_longer_word(target, before, after):
    assume(not re.search(re.escape(target), before + after, re.IGNORECASE))
    counts = [0]
    word = before + target + after
    assert pdf._scrub(word, pdf._patterns(target), counts) == word
    assert counts == [0]
