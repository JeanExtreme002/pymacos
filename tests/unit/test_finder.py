"""Unit tests for :mod:`macos.finder`. They run on any platform."""

import sys
from pathlib import Path

import pytest

import macos
from macos import finder


def test_finder_reveal(fake_run, tmp_path):
    macos.finder.reveal(tmp_path)

    assert fake_run.args == ["open", "-R", str(tmp_path)]


def test_thumbnail_rejects_bad_sizes():
    with pytest.raises(ValueError):
        macos.finder.thumbnail(__file__, size=0)


def test_make_alias_checks_its_paths(tmp_path):
    original = tmp_path / "report.pdf"
    original.write_text("x")
    (tmp_path / "report.pdf alias").write_text("already here")

    with pytest.raises(FileNotFoundError):
        macos.finder.make_alias(tmp_path / "missing.pdf")
    with pytest.raises(FileExistsError):
        macos.finder.make_alias(original)  # "report.pdf alias" is taken
    with pytest.raises(FileExistsError):
        macos.finder.make_alias(original, tmp_path)  # the folder's "report.pdf alias" too
    with pytest.raises(FileNotFoundError):
        macos.finder.make_alias(original, tmp_path / "no" / "folder" / "alias")
    with pytest.raises(ValueError, match="no folder around it"):
        macos.finder.make_alias("/")  # a disk has nothing next to it


def test_watch_tells_what_happened(tmp_path):
    from macos.finder import _CREATED, _RENAMED, _kind

    seen = set()
    new = tmp_path / "new.txt"
    new.write_text("x")
    # FSEvents keeps the "created" flag on later changes: only the first sighting is a creation.
    assert _kind(new, _CREATED, seen) == "created"
    assert _kind(new, _CREATED, seen) == "modified"
    assert _kind(tmp_path / "gone.txt", _CREATED | _RENAMED, seen) == "deleted"
    moved = tmp_path / "moved.txt"
    moved.write_text("x")
    assert _kind(moved, _RENAMED, seen) == "renamed"
    new.unlink()
    assert _kind(new, _CREATED, seen) == "deleted"
    new.write_text("again")
    assert _kind(new, _CREATED, seen) == "created"


def test_watch_needs_a_folder(tmp_path):
    with pytest.raises(NotADirectoryError):
        next(macos.finder.watch(tmp_path / "missing"))
    (tmp_path / "file.txt").write_text("x")
    with pytest.raises(NotADirectoryError):
        macos.finder.wait_for_change(tmp_path / "file.txt")


def test_watch_pattern():
    from macos.finder import _matches

    assert _matches("Report.PDF", "*.pdf")
    assert _matches("photo.png", ["*.pdf", "*.png"]) and not _matches("notes.txt", ["*.pdf", "*.png"])
    assert _matches("anything", None)


def test_finder_selection_and_current_folder(fake_run):
    fake_run.stdout = "/Users/alice/report.pdf\x1e/Users/alice/Photos/\x1e\n"
    assert macos.finder.selection() == [Path("/Users/alice/report.pdf"), Path("/Users/alice/Photos")]
    assert fake_run.args[:2] == ["osascript", "-e"] and "selection" in fake_run.args[2]

    fake_run.stdout = "\n"
    assert macos.finder.selection() == [] and macos.finder.current_folder() is None
    fake_run.stdout = "/Users/alice/Documents/\n"
    assert macos.finder.current_folder() == Path("/Users/alice/Documents")


def test_finder_settings(monkeypatch):
    from macos import defaults, finder

    store, restarts = {}, []
    monkeypatch.setattr(defaults, "read", lambda domain, key=None, default=None: store.get((domain, key), default))
    monkeypatch.setattr(defaults, "write", lambda domain, key, value: store.__setitem__((domain, key), value))
    monkeypatch.setattr(finder, "restart", lambda: restarts.append(1))

    assert finder.show_hidden_files() is False
    finder.set_show_hidden_files()
    finder.set_show_extensions(True)
    finder.set_show_path_bar(False)
    finder.set_show_status_bar(True)
    assert store == {
        ("com.apple.finder", "AppleShowAllFiles"): True,
        ("NSGlobalDomain", "AppleShowAllExtensions"): True,
        ("com.apple.finder", "ShowPathbar"): False,
        ("com.apple.finder", "ShowStatusBar"): True,
    }
    assert finder.show_hidden_files() and finder.show_extensions() and not finder.show_path_bar() and len(restarts) == 4


def test_finder_compress_and_extract_commands(fake_run, tmp_path):
    folder = tmp_path / "Project"
    folder.mkdir()

    assert macos.finder.compress(folder) == tmp_path / "Project.zip"
    assert fake_run.args == ["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(folder), str(tmp_path / "Project.zip")]
    archive = tmp_path / "Project.zip"
    archive.write_bytes(b"zip")
    assert macos.finder.extract(archive, tmp_path / "out") == tmp_path / "out"
    assert fake_run.args == ["ditto", "-x", "-k", str(archive), str(tmp_path / "out")]
    with pytest.raises(ValueError, match="must end in .zip"):
        macos.finder.compress(folder, tmp_path / "Project.tar")


def test_quick_look_returns_at_once(fake_run, monkeypatch, tmp_path):
    import subprocess

    started = []
    monkeypatch.setattr(subprocess, "Popen", lambda args, **kwargs: started.append((args, kwargs["start_new_session"])))
    (tmp_path / "a.txt").write_text("x")

    macos.finder.quick_look(tmp_path / "a.txt")
    assert started == [(["qlmanage", "-p", str(tmp_path / "a.txt")], True)]


@pytest.mark.skipif(sys.platform != "darwin", reason="sets real icons, on files in a temporary folder")
def test_custom_icons(tmp_path):
    from tests.helpers import small_png

    folder, file, logo = tmp_path / "Folder", tmp_path / "notes.txt", tmp_path / "logo.png"
    folder.mkdir()
    file.write_text("notes")
    logo.write_bytes(small_png(64, 64))

    for target, image in ((folder, logo), (file, Path("/System/Applications/Calculator.app"))):
        assert not finder.has_custom_icon(target)
        finder.set_icon(target, image)
        assert finder.has_custom_icon(target)
        finder.remove_icon(target)
        assert not finder.has_custom_icon(target)
    assert list(folder.iterdir()) == []  # the hidden "Icon" file goes too
    with pytest.raises(FileNotFoundError):
        finder.set_icon(tmp_path / "missing", logo)


@pytest.mark.skipif(sys.platform != "darwin", reason="reads extended attributes as macOS keeps them")
def test_custom_icon_errors_are_not_hidden(tmp_path, monkeypatch):
    import ctypes
    import errno

    file = tmp_path / "notes.txt"
    file.write_text("notes")

    class Failing:
        def getxattr(self, *args):
            ctypes.set_errno(errno.EIO)
            return -1

    monkeypatch.setattr(macos._libc, "lib", lambda: Failing())
    with pytest.raises(OSError) as raised:
        finder.has_custom_icon(file)
    assert raised.value.errno == errno.EIO


def test_custom_icon_is_read_from_a_symbolic_link_itself(tmp_path, monkeypatch):
    import ctypes

    link = tmp_path / "link"
    link.symlink_to(tmp_path / "anywhere")
    calls = []

    class Recording:
        def getxattr(self, path, name, buffer, size, position, options):
            calls.append((path, options))
            ctypes.set_errno(macos._libc.ENOATTR)
            return -1

    monkeypatch.setattr(macos._libc, "lib", lambda: Recording())
    assert finder.has_custom_icon(link) is False
    assert calls == [(bytes(link), macos._libc.XATTR_NOFOLLOW)]  # not the target's flags, like the quarantine's


def test_largest_gives_up_walking_after_the_timeout(tmp_path, monkeypatch):
    for index in range(3):
        folder = tmp_path / "folder{}".format(index)
        folder.mkdir()
        (folder / "big.bin").write_bytes(b"x" * 2048)
    clock = {"now": 0.0}

    def tick():
        clock["now"] += 10  # each folder walked takes 10 seconds
        return clock["now"]

    monkeypatch.setattr(finder, "require_macos", lambda: None)
    monkeypatch.setattr(macos.spotlight, "search", lambda query, folder=None: [])  # nothing indexed: walked
    monkeypatch.setattr(finder.time, "monotonic", tick)
    with pytest.raises(TimeoutError, match="took more than 25 seconds"):
        finder.largest(tmp_path, at_least=1024, timeout=25)

    clock["now"] = 0.0
    found = finder.largest(tmp_path, at_least=1024, timeout=None)  # for as long as it takes
    assert sorted(path.parent.name for path, size in found) == ["folder0", "folder1", "folder2"]
    with pytest.raises(ValueError, match="timeout"):
        finder.largest(tmp_path, timeout=0)
