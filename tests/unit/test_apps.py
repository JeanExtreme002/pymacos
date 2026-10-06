"""Unit tests for :mod:`macos.apps`. They run on any platform."""

import sys
from pathlib import Path

import pytest

import macos


def test_open_passes_urls_through_and_checks_paths(fake_run, tmp_path):
    macos.open("https://python.org", background=True)
    assert fake_run.args == ["open", "-g", "-u", "https://python.org"]

    macos.open(tmp_path)
    assert fake_run.args == ["open", "--", str(tmp_path)]

    with pytest.raises(FileNotFoundError):
        macos.open(tmp_path / "missing.pdf")


def test_open_with_resolves_the_app(fake_run, monkeypatch, tmp_path):
    monkeypatch.setattr(macos.apps, "_locate", lambda app: "/Applications/{}.app".format(app))
    target = tmp_path / "photo.png"
    target.touch()

    macos.apps.open_with(target, "Preview")
    assert fake_run.args == ["open", "-a", "/Applications/Preview.app", "--", str(target)]
    assert macos.open_with is macos.apps.open_with  # the short name


def test_open_with_reports_a_missing_app_as_app_not_found(fake_run, monkeypatch, tmp_path):
    monkeypatch.setattr(macos.apps, "_locate", lambda app: "/Applications/Nope.app")
    fake_run.returncode, fake_run.stderr = 1, "LSOpenURLsWithRole() failed with error -10814 for the file /tmp."

    with pytest.raises(macos.AppNotFoundError, match="could not open"):
        macos.open_with(tmp_path, "Nope")


@pytest.mark.parametrize(
    "stderr",
    [
        "The application cannot be opened for an unexpected reason, error=Error Domain=NSOSStatusErrorDomain Code=-10827",
        '"Tool" is damaged and can\'t be opened. You should move it to the Trash.',
    ],
)
def test_open_keeps_the_reason_of_an_app_that_is_there_but_wont_open(fake_run, monkeypatch, tmp_path, stderr):
    monkeypatch.setattr(macos.apps, "_locate", lambda app: "/Applications/Tool.app")
    monkeypatch.setattr(macos.apps, "_bundle_id", lambda path: "com.example.tool")
    fake_run.returncode, fake_run.stderr = 1, stderr

    for attempt in (lambda: macos.open_with(tmp_path, "Tool"), lambda: macos.apps.open("Tool")):
        with pytest.raises(macos.CommandError) as raised:
            attempt()
        assert not isinstance(raised.value, macos.AppNotFoundError) and stderr in str(raised.value)


def test_open_reports_a_missing_app_as_app_not_found(fake_run, monkeypatch):
    monkeypatch.setattr(macos.apps, "_locate", lambda app: "/Applications/Gone.app")
    monkeypatch.setattr(macos.apps, "_bundle_id", lambda path: None)
    fake_run.returncode, fake_run.stderr = 1, "Unable to find application named '/Applications/Gone.app'"

    with pytest.raises(macos.AppNotFoundError, match="unable to launch"):
        macos.apps.open("Gone")


def test_login_items(fake_run, monkeypatch):
    from macos import apps

    fake_run.stdout = "Rectangle\x1f/Applications/Rectangle.app\x1eBackup\x1fmissing value\x1e\n"
    assert apps.login_items() == [
        apps.LoginItem("Rectangle", "/Applications/Rectangle.app"),
        apps.LoginItem("Backup", None),
    ]
    monkeypatch.setattr(apps, "_locate", lambda name: "/Applications/Rectangle.app")
    monkeypatch.setattr(apps.os.path, "realpath", lambda path: path)
    assert apps.add_login_item("Rectangle").name == "Rectangle"  # already there: nothing added
    assert "make login item" not in fake_run.args[2]
    assert apps.remove_login_item("Rectangle") is True
    assert fake_run.args[3:] == ["--", "/Applications/Rectangle.app"]  # removed by path


def test_add_login_item_fails_cleanly_when_it_does_not_show_up(fake_run, monkeypatch):
    from macos import apps

    monkeypatch.setattr(apps, "_locate", lambda name: "/Applications/Tool.app")
    monkeypatch.setattr(apps.os.path, "realpath", lambda path: path)
    fake_run.stdout = "Rectangle\x1f/Applications/Rectangle.app\x1e\n"  # before and after: never added

    with pytest.raises(macos.MacOSError, match="wasn't added"):
        apps.add_login_item("Tool")  # a MacOSError, not a StopIteration


def test_install_from_dmg_checks_the_destination(tmp_path):
    with pytest.raises(NotADirectoryError):
        macos.apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "missing")


def test_install_from_dmg_keeps_the_old_app_when_the_copy_fails(monkeypatch, tmp_path):
    from macos import apps, system

    volume = tmp_path / "Volume"
    (volume / "Tool.app" / "Contents").mkdir(parents=True)
    installed = tmp_path / "Applications" / "Tool.app"
    (installed / "Contents").mkdir(parents=True)
    (installed / "Contents" / "old").write_text("old version")
    monkeypatch.setattr(system, "mount_image", lambda image: volume)
    monkeypatch.setattr(system, "unmount_image", lambda mounted, force=False: None)

    def failing_copy(args):
        Path(args[-1]).mkdir()  # a partial copy
        raise macos.CommandError(args, 1, "No space left on device")

    monkeypatch.setattr(apps, "_run", failing_copy)
    with pytest.raises(macos.CommandError):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications", replace=True)
    assert (installed / "Contents" / "old").read_text() == "old version"  # still installed
    assert sorted(path.name for path in (tmp_path / "Applications").iterdir()) == ["Tool.app"]  # no leftovers


def test_install_from_dmg_keeps_the_first_error_when_unmounting_fails_too(monkeypatch, tmp_path):
    from macos import apps, system

    volume = tmp_path / "Volume"
    (volume / "Tool.app" / "Contents").mkdir(parents=True)
    (tmp_path / "Applications").mkdir()

    def stuck(mounted, force=False):
        raise macos.CommandError(["hdiutil", "detach"], 16, "resource busy")

    def failing_copy(args):
        raise macos.CommandError(args, 1, "No space left on device")

    monkeypatch.setattr(system, "mount_image", lambda image: volume)
    monkeypatch.setattr(system, "unmount_image", stuck)
    monkeypatch.setattr(apps, "_run", failing_copy)
    with pytest.raises(macos.CommandError, match="No space left"):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications")

    # Installed, but the image stays mounted: that is worth an error of its own.
    monkeypatch.setattr(apps, "_run", lambda args: Path(args[-1]).mkdir())
    with pytest.raises(macos.CommandError, match="resource busy"):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications")
    assert (tmp_path / "Applications" / "Tool.app").is_dir()


@pytest.mark.skipif(sys.platform != "darwin", reason="extended attributes as macOS keeps them")
def test_unquarantine(tmp_path):
    import subprocess

    app = tmp_path / "Tool.app"
    (app / "Contents").mkdir(parents=True)
    binary = app / "Contents" / "tool"
    binary.write_text("")
    for path in (app, binary):
        subprocess.run(["/usr/bin/xattr", "-w", "com.apple.quarantine", "0081;00000000;Safari;", str(path)], check=True)

    assert macos.apps.is_quarantined(app) and macos.apps.is_quarantined(binary)
    assert macos.apps.unquarantine(app) == 2
    assert not macos.apps.is_quarantined(app) and not macos.apps.is_quarantined(binary)
    assert macos.apps.unquarantine(app) == 0
    with pytest.raises(FileNotFoundError):
        macos.apps.is_quarantined(tmp_path / "missing.app")


@pytest.mark.skipif(sys.platform != "darwin", reason="extended attributes as macOS keeps them")
def test_is_quarantined_reports_errors_other_than_a_missing_mark(tmp_path, monkeypatch):
    import ctypes
    import errno

    file = tmp_path / "file"
    file.write_text("")

    class Failing:
        def getxattr(self, *args):
            ctypes.set_errno(errno.EACCES)
            return -1

    monkeypatch.setattr(macos._libc, "lib", lambda: Failing())
    with pytest.raises(PermissionError):
        macos.apps.is_quarantined(file)


@pytest.mark.skipif(sys.platform != "darwin", reason="extended attributes as macOS keeps them")
def test_unquarantine_keeps_the_error_and_stops_at_unreadable_folders(tmp_path, monkeypatch):
    import ctypes
    import errno

    app = tmp_path / "Tool.app"
    (app / "Contents").mkdir(parents=True)

    class Failing:
        def removexattr(self, *args):
            ctypes.set_errno(errno.EIO)
            return -1

    monkeypatch.setattr(macos._libc, "lib", lambda: Failing())
    with pytest.raises(OSError) as raised:
        macos.apps.unquarantine(app)
    assert raised.value.errno == errno.EIO and not isinstance(raised.value, PermissionError)

    monkeypatch.undo()
    locked = app / "Contents" / "Locked"
    locked.mkdir()
    locked.chmod(0)
    try:
        with pytest.raises(PermissionError):
            macos.apps.unquarantine(app)
    finally:
        locked.chmod(0o755)


def test_uninstall_finds_the_leftovers_by_bundle_id_and_name(tmp_path):
    from macos.apps import _leftovers

    library = tmp_path / "Library"
    mine = [
        "Application Support/com.example.Chat",
        "Application Support/Chat",
        "Caches/com.example.Chat",
        "Caches/com.example.Chat.ShipIt",
        "Containers/com.example.Chat.helper",
        "Group Containers/ABCDE12345.com.example.Chat",
        "HTTPStorages/com.example.Chat.binarycookies",
        "Logs/Chat",
        "Preferences/com.example.Chat.plist",
        "Preferences/ByHost/com.example.Chat.0F1E2D3C.plist",
        "Saved Application State/com.example.Chat.savedState",
    ]
    others = [
        "Application Support/com.example.ChatPro",  # another app whose ID starts the same
        "Application Support/Chatter",
        "Preferences/com.example.Chat2.plist",
        "Preferences/Chat.plist",  # the name only counts in Application Support, Caches and Logs
        "Group Containers/group.com.example.Chatbot",
        "Documents/Chat",
    ]
    for entry in mine + others:
        (library / entry).mkdir(parents=True)

    found = _leftovers(library, "com.example.Chat", ["Chat"])

    assert sorted(found) == sorted(library / entry for entry in mine)
    # Another installed app whose ID starts with this one's keeps its files.
    found = _leftovers(library, "com.example.Chat", ["Chat"], others=["com.example.Chat.ShipIt"])
    assert library / "Caches/com.example.Chat.ShipIt" not in found and library / "Caches/com.example.Chat" in found
    assert _leftovers(library, None, ["Nothing"]) == []


def test_uninstall_leaves_the_names_and_ids_of_other_apps_alone():
    from macos.apps import InstalledApp, _claims

    chat = InstalledApp(name="Chat", bundle_id="com.example.Chat", version="1", path=Path("/Applications/Chat.app"))
    everything = [
        chat,
        InstalledApp(name="chat", bundle_id="org.other.chat", version="2", path=Path("/Applications/Other Chat.app")),
        InstalledApp(name="Chat Helper", bundle_id="com.example.Chat.helper", version="1", path=Path("/Applications/H.app")),
        InstalledApp(name="Chat", bundle_id="com.example.Chat", version="0.9", path=Path("/Users/me/Downloads/Chat.app")),
    ]

    names, others = _claims(chat, everything)

    assert names == []  # another app is called "chat": its Application Support folder may be that one's
    assert others == ["com.example.Chat.helper"]  # an old copy of the same app isn't another app
    assert _claims(chat, [chat]) == (["Chat"], [])


def test_uninstall_skips_names_a_sibling_app_may_share():
    from macos.apps import InstalledApp, _claims

    def app(name, bundle_id, path):
        return InstalledApp(name=name, bundle_id=bundle_id, version="1", path=Path(path))

    firefox = app("Firefox", "org.mozilla.firefox", "/Applications/Firefox.app")
    developer = app("Firefox Developer Edition", "org.mozilla.firefoxdeveloperedition", "/Applications/FD.app")
    nightly = app("Firefox Nightly", "com.other.nightly", "/Applications/Firefox Nightly.app")
    slack = app("Slack", "com.tinyspeck.slackmacgap", "/Applications/Slack.app")

    assert _claims(firefox, [firefox, developer])[0] == []  # the same maker: Application Support/Firefox is shared
    assert _claims(firefox, [firefox, nightly])[0] == []  # another app's name holds "Firefox"
    assert _claims(slack, [slack, firefox, developer, nightly])[0] == ["Slack"]


def test_uninstall_moves_name_matches_only_when_asked(tmp_path, monkeypatch):
    import plistlib

    from macos import apps

    bundle = tmp_path / "Applications" / "Chat.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleName": "Chat", "CFBundleIdentifier": "com.example.Chat"})
    )
    home = tmp_path / "home"
    for entry in ("Application Support/Chat", "Caches/com.example.Chat"):
        (home / "Library" / entry).mkdir(parents=True)
    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(apps, "_locate", lambda name: str(bundle))
    monkeypatch.setattr(apps, "installed", lambda: [apps._installed_app(str(bundle))])
    monkeypatch.setattr(apps.Path, "home", lambda: home)

    assert apps.uninstall("Chat", dry_run=True) == [bundle, home / "Library/Caches/com.example.Chat"]
    assert apps.uninstall("Chat", dry_run=True, include_name_matches=True) == [
        bundle, home / "Library/Caches/com.example.Chat", home / "Library/Application Support/Chat",  # the names last
    ]
