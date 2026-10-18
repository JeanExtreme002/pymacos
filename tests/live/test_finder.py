"""Tests of :mod:`macos.finder` against the real system. Skipped outside macOS."""

import os
import uuid
from pathlib import Path

import pytest

import macos


def test_finder_tags(tmp_path):
    path = tmp_path / "tagged.txt"
    path.write_text("hi")

    assert macos.finder.tags(path) == []
    assert macos.finder.add_tags(path, "pymacos-a", "pymacos-b", "pymacos-a") == ["pymacos-a", "pymacos-b"]
    assert macos.finder.remove_tags(path, "pymacos-a", "missing") == ["pymacos-b"]
    macos.finder.set_tags(path, [])
    assert macos.finder.tags(path) == []


def test_finder_trash(tmp_path):
    path = tmp_path / "trash me {}.txt".format(uuid.uuid4())
    path.write_text("bye")

    trashed = macos.finder.trash(path)
    try:
        assert not path.exists()
        assert trashed.exists()
        assert ".Trash" in trashed.parts
    finally:
        trashed.unlink(missing_ok=True)


def test_finder_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        macos.finder.tags(tmp_path / "missing")


def test_thumbnail_rejects_huge_sizes():
    with pytest.raises(ValueError):
        macos.finder.thumbnail("/System/Library/CoreServices/Finder.app", size=100000)


def test_thumbnail_of_an_app_is_its_icon_at_the_requested_size():
    import struct

    image = macos.finder.thumbnail("/System/Library/CoreServices/Finder.app", size=64)
    width, height = struct.unpack(">II", image[16:24])  # the PNG header
    assert max(width, height) == 64


def test_finder_aliases(tmp_path):
    original = tmp_path / "report.pdf"
    original.write_text("x")
    folder = tmp_path / "Folder"
    folder.mkdir()

    alias = macos.finder.make_alias(original)
    assert alias == tmp_path / "report.pdf alias"
    assert macos.finder.is_alias(alias) and not macos.finder.is_alias(original)
    assert macos.finder.resolve_alias(alias).name == "report.pdf"
    assert macos.finder.resolve_alias(original) == original  # not an alias: as it is
    # Python itself sees a plain file.
    assert Path(os.path.realpath(alias)).name == "report.pdf alias"

    inside = macos.finder.make_alias(original, folder)
    assert inside == folder / "report.pdf alias"
    assert macos.finder.resolve_alias(macos.finder.make_alias(folder, tmp_path / "To folder")).name == "Folder"
    assert macos.finder.resolve_alias(macos.finder.make_alias(alias, tmp_path / "Alias of alias")).name == "report.pdf"
    link = tmp_path / "link"
    link.symlink_to(alias)
    assert not macos.finder.is_alias(link)
    assert macos.finder.resolve_alias(link).name == "report.pdf"

    # A disk has no name of its own: the alias takes the one Finder shows.
    disk = macos.finder.make_alias("/", tmp_path)
    assert disk.name.endswith(" alias") and disk.name != " alias"
    assert macos.finder.resolve_alias(disk) == Path("/")

    # An alias follows its original when it's moved and renamed...
    original.rename(folder / "moved.pdf")
    assert macos.finder.resolve_alias(alias).name == "moved.pdf"
    # ...but not when it's deleted.
    (folder / "moved.pdf").unlink()
    with pytest.raises(FileNotFoundError, match="original of the alias"):
        macos.finder.resolve_alias(alias)


def test_make_alias_keeps_the_name_asked_for(tmp_path):
    import unicodedata

    original = tmp_path / "report.pdf"
    original.write_text("x")
    name = unicodedata.normalize("NFC", "Relatório")  # composed, as typed: not decomposed on the way
    alias = macos.finder.make_alias(original, tmp_path / name)
    assert alias.name == name and name in os.listdir(tmp_path)
    assert macos.finder.resolve_alias(alias).name == "report.pdf"


def test_watch_reports_changes_as_they_happen(tmp_path):
    import threading
    import time

    folder = tmp_path / "watched"
    folder.mkdir()
    (folder / "sub").mkdir()

    def work():
        time.sleep(0.5)
        (folder / "new.txt").write_text("x")
        time.sleep(0.3)
        (folder / "new.txt").rename(folder / "renamed.txt")
        time.sleep(0.3)
        (folder / "sub" / "deep.txt").write_text("x")
        time.sleep(0.3)
        (folder / "renamed.txt").unlink()

    threading.Thread(target=work).start()
    seen = {}
    for event in macos.finder.watch(folder, timeout=4):
        seen.setdefault(event.path.name, []).append(event.kind)
        if "deleted" in seen.get("renamed.txt", []):
            break

    assert seen["new.txt"][0] == "created" and seen["new.txt"][-1] == "deleted"
    assert seen["renamed.txt"][0] == "renamed" and seen["renamed.txt"][-1] == "deleted"
    assert seen["deep.txt"][0] == "created"

    threading.Timer(0.5, lambda: (folder / "sub" / "ignored.txt").write_text("x")).start()
    assert macos.finder.wait_for_change(folder, recursive=False, timeout=1.5) is None
    assert macos.finder.wait_for_change(folder, timeout=0.3) is None


def test_watch_a_folder_named_in_another_case(tmp_path):
    import threading

    folder = tmp_path / "CaseDir"
    folder.mkdir()
    threading.Timer(0.5, lambda: (folder / "new.txt").write_text("x")).start()
    # The disk ignores case; FSEvents names what changed as the disk spells it.
    event = macos.finder.wait_for_change(tmp_path / "casedir", recursive=False, timeout=5)
    assert event is not None and event.path.name == "new.txt" and event.path.parent.name == "CaseDir"


def test_watch_pattern(tmp_path):
    import threading
    import time

    def work():
        time.sleep(0.5)
        (tmp_path / "notes.txt").write_text("x")
        (tmp_path / "Report.PDF").write_text("x")

    threading.Thread(target=work).start()
    event = macos.finder.wait_for_change(tmp_path, pattern="*.pdf", timeout=5)
    assert event is not None and event.path.name == "Report.PDF"


def test_compress_and_extract_keep_the_tags(tmp_path):
    folder = tmp_path / "Project"
    (folder / "sub").mkdir(parents=True)
    (folder / "a.txt").write_text("hi")
    (folder / "sub" / "b.txt").write_text("deep")
    macos.finder.add_tags(folder / "a.txt", "Red")

    archive = macos.finder.compress(folder)
    out = macos.finder.extract(archive, tmp_path / "out")
    assert sorted(path.relative_to(out).as_posix() for path in out.rglob("*")) == [
        "Project", "Project/a.txt", "Project/sub", "Project/sub/b.txt",
    ]  # fmt: skip
    assert macos.finder.tags(out / "Project" / "a.txt") == ["Red"]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its permissions: ditto wouldn't fail")
def test_compress_keeps_the_old_archive_when_it_fails(tmp_path):
    folder = tmp_path / "Project"
    folder.mkdir()
    (folder / "a.txt").write_text("hi")
    archive = macos.finder.compress(folder)
    before = archive.read_bytes()

    unreadable = folder / "locked.txt"
    unreadable.write_text("secret")
    unreadable.chmod(0)
    try:
        with pytest.raises(macos.CommandError):
            macos.finder.compress(folder)
    finally:
        unreadable.chmod(0o600)
    assert archive.read_bytes() == before
    assert sorted(path.name for path in tmp_path.iterdir()) == ["Project", "Project.zip"]  # nothing left behind


def test_extract_refuses_to_write_over_files_when_asked(tmp_path):
    folder = tmp_path / "Project"
    folder.mkdir()
    (folder / "a.txt").write_text("new")
    archive = macos.finder.compress(folder)
    out = tmp_path / "out"
    (out / "Project").mkdir(parents=True)
    (out / "Project" / "a.txt").write_text("old")

    with pytest.raises(FileExistsError):
        macos.finder.extract(archive, out, overwrite=False)
    assert (out / "Project" / "a.txt").read_text() == "old"
    macos.finder.extract(archive, out, overwrite=True)
    assert (out / "Project" / "a.txt").read_text() == "new"


def test_extract_sees_accented_names_and_compress_into_its_folder_stays_the_same(tmp_path):
    folder = tmp_path / "Projeto"
    folder.mkdir()
    (folder / "relatório.txt").write_text("new")
    archive = macos.finder.compress(folder)
    out = tmp_path / "out"
    (out / "Projeto").mkdir(parents=True)
    (out / "Projeto" / "relatório.txt").write_text("old")

    # ditto stores UTF-8 names without the zip's UTF-8 flag: read as cp437 they'd match nothing.
    with pytest.raises(FileExistsError, match="relatório"):
        macos.finder.extract(archive, out, overwrite=False)

    # An archive kept in the folder it zips doesn't take in a copy of itself, run after run.
    inside = folder / "Projeto.zip"
    sizes = [macos.finder.compress(folder, inside).stat().st_size for _ in range(3)]
    assert sizes[1] == sizes[2] and sorted(path.name for path in folder.iterdir()) == ["Projeto.zip", "relatório.txt"]


def test_finder_settings_are_read():
    for read in (macos.finder.show_hidden_files, macos.finder.show_extensions, macos.finder.show_path_bar):
        assert isinstance(read(), bool)
