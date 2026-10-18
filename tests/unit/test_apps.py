"""Unit tests for :mod:`macos.apps`. They run on any platform."""

import sys
from pathlib import Path

import warnings

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
    monkeypatch.setattr(macos.apps, "_running_pids", lambda bundle_id: ())  # asked of Objective-C: not on Linux
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
    monkeypatch.setattr(apps, "get", lambda name: None)  # not running

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


def test_install_from_dmg_never_follows_a_link_named_like_an_app(monkeypatch, tmp_path):
    from macos import apps, system

    volume = tmp_path / "Volume"
    volume.mkdir()
    elsewhere = tmp_path / "Private"
    (elsewhere / "Contents").mkdir(parents=True)
    (volume / "Tool.app").symlink_to(elsewhere)  # ditto would copy the folder it points to
    (tmp_path / "Applications").mkdir()
    copied = []
    monkeypatch.setattr(system, "mount_image", lambda image: volume)
    monkeypatch.setattr(system, "unmount_image", lambda mounted, force=False: None)
    monkeypatch.setattr(apps, "_run", copied.append)

    with pytest.raises(macos.AppNotFoundError, match=r"has no app at its top \(Tool.app is a symbolic link"):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications")
    assert copied == []

    # Beside a real app, the link is left out: no warning about several apps, and app= can't pick it.
    (volume / "Real.app" / "Contents").mkdir(parents=True)
    with pytest.raises(macos.AppNotFoundError, match=r"it holds Real.app \(Tool.app is a symbolic link, not installed\)"):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications", app="Tool")
    monkeypatch.setattr(apps, "_run", lambda args: (copied.append(args), Path(args[-1]).mkdir()))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        installed = apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications")
    assert installed.endswith("Real.app")
    assert [Path(args[1]).name for args in copied] == ["Real.app"]


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


def test_quarantine_checks_the_path_without_taking_an_empty_one_for_the_current_folder(tmp_path, monkeypatch):
    import ctypes
    import os

    asked = []

    class Unmarked:
        def getxattr(self, path, *args):
            asked.append(path)
            ctypes.set_errno(macos._libc.ENOATTR)
            return -1

        def removexattr(self, path, *args):
            asked.append(path)
            ctypes.set_errno(macos._libc.ENOATTR)
            return -1

    monkeypatch.setattr(macos._libc, "lib", lambda: Unmarked())
    monkeypatch.chdir(tmp_path)
    (tmp_path / "file").write_text("")
    for function in (macos.apps.is_quarantined, macos.apps.unquarantine):
        with pytest.raises(FileNotFoundError):
            function("")  # not the current folder, and all it holds
        with pytest.raises(FileNotFoundError):
            function(tmp_path / "missing.app")
        with pytest.raises(FileNotFoundError):
            function(tmp_path / "file" / "below")  # under a file: missing, not "not a directory"
    assert asked == []

    # A broken link has a mark of its own: it is there.
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "gone")
    assert macos.apps.is_quarantined(link) is False and macos.apps.unquarantine(link) == 0

    # A file in a folder that can't be looked in isn't called missing.
    locked = tmp_path / "locked"
    locked.mkdir()
    (locked / "file").write_text("")
    locked.chmod(0)
    try:
        if os.access(locked, os.X_OK):
            pytest.skip("running as root: every folder can be looked in")
        for function in (macos.apps.is_quarantined, macos.apps.unquarantine):
            with pytest.raises(PermissionError):
                function(locked / "file")
    finally:
        locked.chmod(0o755)


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


def test_uninstall_claims_no_other_app_files_by_a_short_bundle_id(tmp_path):
    from macos.apps import _leftovers, _owned_by

    # An app calling itself "com.google" would otherwise take every Google app's files with it.
    library = tmp_path / "Library"
    for entry in (
        "Preferences/com.google.plist",
        "Preferences/com.google.Chrome.plist",
        "Caches/com.google.Keystone",
        "Group Containers/EQHXZ8M8AV.com.google",
    ):
        (library / entry).mkdir(parents=True)

    assert _leftovers(library, "com.google", []) == [library / "Preferences/com.google.plist"]  # its own only
    assert _owned_by("com.apple.dt.Xcode.plist", "com.apple.dt.Xcode")  # a full ID: its own and its helpers'
    assert _owned_by("com.apple.dt.Xcode.helper", "com.apple.dt.Xcode")
    assert not _owned_by("com.google.Chrome", "com.google")


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
    monkeypatch.setattr(apps, "_installed", lambda: [apps._installed_app(str(bundle))])
    monkeypatch.setattr(apps.Path, "home", lambda: home)

    assert apps.uninstall("Chat", dry_run=True) == [bundle, home / "Library/Caches/com.example.Chat"]
    assert apps.uninstall("Chat", dry_run=True, include_name_matches=True) == [
        bundle, home / "Library/Caches/com.example.Chat", home / "Library/Application Support/Chat",  # the names last
    ]


def _dmg_with_tool_installed(monkeypatch, tmp_path):
    from macos import apps, system

    volume = tmp_path / "Volume"
    (volume / "Tool.app" / "Contents").mkdir(parents=True)
    installed = tmp_path / "Applications" / "Tool.app"
    (installed / "Contents").mkdir(parents=True)
    (installed / "Contents" / "old").write_text("old version")
    unmounted = []
    monkeypatch.setattr(system, "mount_image", lambda image: volume)
    monkeypatch.setattr(system, "unmount_image", lambda mounted, force=False: unmounted.append(mounted))
    monkeypatch.setattr(apps, "_run", lambda args: Path(args[-1]).mkdir())
    return installed, unmounted


def test_install_from_dmg_refuses_to_replace_a_running_app(monkeypatch, tmp_path):
    from macos import apps

    installed, unmounted = _dmg_with_tool_installed(monkeypatch, tmp_path)
    monkeypatch.setattr(apps, "get", lambda name: apps.App(name="Tool", bundle_id=None, pid=42, path=name))

    with pytest.raises(macos.MacOSError, match="Tool is running: quit it first"):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications", replace=True)
    assert (installed / "Contents" / "old").read_text() == "old version"
    assert unmounted  # the image is unmounted all the same


def test_install_from_dmg_checks_the_copy_it_replaces_not_an_app_of_that_name(monkeypatch, tmp_path):
    from macos import apps

    installed, _ = _dmg_with_tool_installed(monkeypatch, tmp_path)
    asked = []
    monkeypatch.setattr(apps, "get", lambda name: asked.append(name))
    monkeypatch.chdir(tmp_path / "Applications")

    apps.install_from_dmg(tmp_path / "Tool.dmg", destination=".", replace=True)
    assert asked == [str(installed)]  # "Tool.app" alone would be any running app called Tool


def test_install_from_dmg_knows_the_running_app_spelled_another_way(monkeypatch, tmp_path):
    from macos import apps

    installed, _ = _dmg_with_tool_installed(monkeypatch, tmp_path)
    (tmp_path / "Volume" / "Tool.app").rename(tmp_path / "Volume" / "tool.app")  # the image spells it in lower case
    if not (installed.parent / "tool.app").exists():
        pytest.skip("this disk tells names apart by case: the two are different apps on it")
    # Running apps are known by the path as the disk spells it.
    monkeypatch.setattr(apps, "get", lambda path: apps.App("Tool", None, 42, path) if path == str(installed) else None)

    with pytest.raises(macos.MacOSError, match="is running: quit it first"):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications", replace=True)
    assert (installed / "Contents" / "old").read_text() == "old version"


def test_install_from_dmg_warns_when_the_old_copy_stays(monkeypatch, tmp_path):
    from macos import apps

    installed, _ = _dmg_with_tool_installed(monkeypatch, tmp_path)
    monkeypatch.setattr(apps, "get", lambda name: None)
    monkeypatch.setattr(apps.shutil, "rmtree", lambda path, ignore_errors=False: None)  # root-owned files: nothing goes

    with pytest.warns(RuntimeWarning, match="delete .*replaced-.* yourself"):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications", replace=True)
    assert not (installed / "Contents" / "old").exists()  # the new copy is in place


def test_setting_a_default_app_reuses_one_completion_block(monkeypatch):
    import functools

    from macos import apps

    made, sent = [], []
    monkeypatch.setattr(apps._objc, "block", lambda function, *types: made.append(function) or len(made))
    monkeypatch.setattr(apps, "_default_handler", functools.lru_cache(maxsize=None)(apps._default_handler.__wrapped__))
    monkeypatch.setattr(apps, "_default_generation", [0])
    monkeypatch.setattr(apps, "_default_answers", [])
    monkeypatch.setattr(apps, "framework", lambda name: None)
    monkeypatch.setattr(apps._objc, "cls", lambda name: 1)
    monkeypatch.setattr(apps._objc, "nsstring", lambda text: 1)
    monkeypatch.setattr(apps._objc, "file_url", lambda path: 1)

    def send(receiver, selector, *args, **kwargs):
        if selector.startswith("setDefaultApplication"):
            sent.append(args[2])  # the block
        return 1

    monkeypatch.setattr(apps._objc, "send", send)
    answer = {"now": True}

    def run_until(done, timeout):
        if answer["now"]:
            made[sent[-1] - 1](None)  # macOS calls the block: no error
        return done()

    monkeypatch.setattr(apps._objc, "run_until", run_until)
    for _ in range(3):
        apps._set_default_with_workspace(1, "/Applications/Tool.app", "public.plain-text", "Tool", "txt", 5)
    assert len(made) == 1 and sent == [1, 1, 1]  # no block per call

    answer["now"] = False
    with pytest.raises(macos.WaitTimeoutError, match="wasn't confirmed"):
        apps._set_default_with_workspace(1, "/Applications/Tool.app", "public.plain-text", "Tool", "txt", 5)
    made[0](None)  # the given-up call's late answer: retired, it answers nothing
    assert apps._default_answers == []
    answer["now"] = True
    apps._set_default_with_workspace(1, "/Applications/Tool.app", "public.plain-text", "Tool", "txt", 5)
    assert len(made) == 2  # a new block after the timeout only


def test_waiting_for_another_default_app_change_counts_against_the_timeout(monkeypatch):
    import threading

    from macos import apps

    sent = []
    monkeypatch.setattr(apps, "framework", lambda name: None)
    monkeypatch.setattr(apps._objc, "cls", lambda name: 1)
    monkeypatch.setattr(apps._objc, "nsstring", lambda text: 1)
    monkeypatch.setattr(apps._objc, "send", lambda receiver, selector, *args, **kwargs: sent.append(selector) or 1)
    monkeypatch.setattr(apps, "_default_call", threading.Lock())

    apps._default_call.acquire()  # another call, waiting for the user to confirm its change
    try:
        with pytest.raises(macos.WaitTimeoutError, match="within 0.2 seconds"):
            apps._set_default_with_workspace(1, "/Applications/Tool.app", "public.plain-text", "Tool", "txt", 0.2)
    finally:
        apps._default_call.release()
    assert not any(selector.startswith("setDefaultApplication") for selector in sent)  # never asked: out of time


def test_uninstall_says_which_library_folders_it_could_not_look_in(tmp_path, monkeypatch):
    """Cookies is protected on every Mac: without Full Disk Access the uninstall goes on, and says what it couldn't see."""
    import plistlib

    from macos import apps

    bundle = tmp_path / "Applications" / "Chat.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleName": "Chat", "CFBundleIdentifier": "com.example.Chat"})
    )
    home = tmp_path / "home"
    library = home / "Library"
    (library / "Caches" / "com.example.Chat").mkdir(parents=True)
    (library / "Cookies").mkdir()
    listdir = apps.os.listdir

    def protected(path):
        if str(path).endswith("/Cookies"):
            raise PermissionError(1, "Operation not permitted", str(path))  # EPERM: how TCC refuses
        return listdir(path)

    monkeypatch.setattr(apps.os, "listdir", protected)
    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(apps, "_locate", lambda name: str(bundle))
    monkeypatch.setattr(apps, "_installed", lambda: [apps._installed_app(str(bundle))])
    monkeypatch.setattr(apps.Path, "home", lambda: home)

    with pytest.warns(RuntimeWarning, match="Cookies couldn't be looked in.*Full Disk Access is missing") as caught:
        assert apps.uninstall("Chat", dry_run=True) == [bundle, library / "Caches" / "com.example.Chat"]
    assert caught[0].filename == __file__  # the warning points at the caller
    # A folder that isn't there is nothing of the app's: no warning.
    (library / "Cookies").rmdir()
    monkeypatch.setattr(apps.os, "listdir", listdir)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert apps.uninstall("Chat", dry_run=True) == [bundle, library / "Caches" / "com.example.Chat"]


def test_installed_gives_spotlight_a_timeout(tmp_path, monkeypatch):
    """A stuck Spotlight mustn't hang installed(), and uninstall() with it: the folders alone are listed then."""
    from macos import apps

    queries = []

    def search(query, **options):
        queries.append(options)
        raise macos.CommandTimeoutError(["mdfind", query], options["timeout"])

    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(apps, "_APP_FOLDERS", (str(tmp_path),))
    monkeypatch.setattr(apps.spotlight, "search", search)
    bundle = tmp_path / "Tool.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(
        b'<plist version="1.0"><dict><key>CFBundleName</key><string>Tool</string></dict></plist>'
    )

    with pytest.warns(RuntimeWarning, match="Spotlight couldn't be asked") as reported:
        assert [app.name for app in apps.installed()] == ["Tool"]
    assert queries and queries[0]["timeout"] == apps._SPOTLIGHT_TIMEOUT > 0
    # uninstall() lists the installed apps too: its warning points at the call to it, not inside the package.
    monkeypatch.setattr(apps, "_locate", lambda name: str(bundle))
    monkeypatch.setattr(apps.Path, "home", lambda: tmp_path / "home")
    with pytest.warns(RuntimeWarning, match="Spotlight couldn't be asked") as reported_too:
        assert apps.uninstall("Tool", dry_run=True) == [bundle]
    assert reported[0].filename == reported_too[0].filename == __file__


def test_install_from_dmg_with_several_apps_warns_or_takes_the_one_named(monkeypatch, tmp_path):
    from macos import apps, system

    volume = tmp_path / "Volume"
    for name in ("Editor.app", "Viewer.app", "Read Me.rtf"):
        (volume / name).mkdir(parents=True)
    applications = tmp_path / "Applications"
    applications.mkdir()
    monkeypatch.setattr(system, "mount_image", lambda image: volume)
    monkeypatch.setattr(system, "unmount_image", lambda mounted, force=False: None)
    monkeypatch.setattr(apps, "get", lambda name: None)  # not running
    monkeypatch.setattr(apps, "_run", lambda args: Path(args[-1]).mkdir())

    # Nothing chosen: the first by name, with a word about the others, pointing at the caller.
    with pytest.warns(RuntimeWarning, match=r"holds several apps \(Editor.app, Viewer.app\): installing Editor.app") as caught:
        assert apps.install_from_dmg(tmp_path / "Suite.dmg", destination=applications) == str(applications / "Editor.app")
    assert caught[0].filename == __file__
    # Named, with or without .app, in any case: that one, and no warning.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        installed = apps.install_from_dmg(tmp_path / "Suite.dmg", destination=applications, app="viewer")
        assert installed == str(applications / "Viewer.app")
        again = apps.install_from_dmg(tmp_path / "Suite.dmg", destination=applications, app="Viewer.app", replace=True)
        assert again == installed
    with pytest.raises(macos.AppNotFoundError, match="has no app named 'Player': it holds Editor.app, Viewer.app"):
        apps.install_from_dmg(tmp_path / "Suite.dmg", destination=applications, app="Player")
    assert sorted(path.name for path in applications.iterdir()) == ["Editor.app", "Viewer.app"]


def test_uninstall_says_when_the_app_itself_cannot_be_read(tmp_path, monkeypatch):
    """An Info.plist that can't be read is a permission problem, not "isn't an app"; a listing skips it all the same."""
    import functools
    import os
    import plistlib

    from macos import apps

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root reads every file")
    bundle = tmp_path / "Applications" / "Chat.app"
    (bundle / "Contents").mkdir(parents=True)
    info = bundle / "Contents" / "Info.plist"
    info.write_bytes(plistlib.dumps({"CFBundleName": "Chat", "CFBundleIdentifier": "com.example.Chat"}))
    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(apps, "_locate", lambda name: str(bundle))
    monkeypatch.setattr(apps, "_APP_FOLDERS", (str(tmp_path / "Applications"),))
    monkeypatch.setattr(apps.spotlight, "search", lambda query, **options: [])
    monkeypatch.setattr(apps.Path, "home", lambda: tmp_path / "home")

    info.chmod(0)
    try:
        with pytest.raises(PermissionError):
            apps.uninstall("Chat", dry_run=True)
        assert apps.installed() == []  # one app that can't be read doesn't fail the listing
    finally:
        info.chmod(0o644)
    assert [app.name for app in apps.installed()] == ["Chat"]
    assert apps.uninstall("Chat", dry_run=True)[0] == bundle
    # A folder that isn't an app at all is still "isn't an app": no Info.plist, a folder in its place
    # (IsADirectoryError), or a malformed one. plistlib's XML parser lets out what it trips on, none of
    # it a ValueError: cut-off XML (ExpatError), a date it can't read (AttributeError), a key outside a
    # dict (IndexError), an unknown encoding (LookupError).
    info.unlink()
    with pytest.raises(macos.AppNotFoundError, match="isn't an app"):
        apps.uninstall("Chat", dry_run=True)
    malformed = (
        b"<?xml version='1.0'?><plist><dict><key>",
        b"<plist><dict><key>k</key><date>yesterday</date></dict></plist>",
        b"<plist><key>k</key></plist>",
        b"<?xml version='1.0' encoding='bogus'?><plist/>",
    )
    for broken in (info.mkdir, *(functools.partial(info.write_bytes, raw) for raw in malformed)):
        if info.is_dir():
            info.rmdir()
        broken()
        with pytest.raises(macos.AppNotFoundError, match="isn't an app"):
            apps.uninstall("Chat", dry_run=True)
        assert apps.installed() == []


def test_installed_says_why_spotlight_was_not_asked(tmp_path, monkeypatch):
    """A permission Spotlight lacks is as silent as Spotlight being off: the listing still comes, and says why."""
    from macos import apps

    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(apps, "_APP_FOLDERS", (str(tmp_path),))
    bundle = tmp_path / "Tool.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(
        b'<plist version="1.0"><dict><key>CFBundleName</key><string>Tool</string></dict></plist>'
    )
    for problem in (macos.PermissionDeniedError("Full Disk Access is missing"), macos.NotSupportedError("no Spotlight")):

        def search(query, **options):
            raise problem

        monkeypatch.setattr(apps.spotlight, "search", search)
        with pytest.warns(RuntimeWarning, match="only those are listed: {}".format(problem)):
            assert [app.name for app in apps.installed()] == ["Tool"]
    monkeypatch.setattr(apps.spotlight, "search", lambda query, **options: [])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert [app.name for app in apps.installed()] == ["Tool"]  # Spotlight answered: nothing to say


class _FakeObjC:
    """Enough of the Objective-C bridge for the questions about running apps."""

    def __init__(self, handles, terminated=(), inactive=()):
        self.handles, self.terminated, self.inactive, self.sent = handles, set(terminated), set(inactive), []
        self.id = object

    def send(self, receiver, selector, *args, **kwargs):
        self.sent.append(selector)
        if selector == "isTerminated":
            return receiver in self.terminated
        if selector == "isActive":
            return receiver not in self.inactive
        if selector == "processIdentifier":
            return receiver
        return 1

    def nsarray(self, obj):
        return list(self.handles)

    def nsstring(self, text):
        return text

    def autorelease_pool(self):
        import contextlib

        return contextlib.nullcontext()


def test_handles_with_bundle_id_asks_about_that_app_alone(monkeypatch):
    from macos import apps

    objc = _FakeObjC([11, 12], terminated=[12])
    monkeypatch.setattr(apps, "_objc", objc)
    monkeypatch.setattr(apps, "_running_application_class", lambda: 1)

    assert apps._handles_with_bundle_id("com.apple.dock") == [11]  # the one that has quit is left out
    assert objc.sent[0] == "runningApplicationsWithBundleIdentifier:"  # one question, not a scan of every process
    assert apps._running_pids("com.apple.dock") == [11] and apps._running_pids(None) == ()


def test_open_returns_a_copy_of_the_app_running_from_elsewhere(fake_run, monkeypatch):
    """macOS brings a running copy (the same bundle ID, another path) to the front rather than open the one asked for."""
    from macos import apps

    asked = "/Volumes/Disk/Tool.app"
    running = apps.App("Tool", "com.example.tool", 7, "/Applications/Tool.app")
    monkeypatch.setattr(apps, "_locate", lambda name: asked)
    monkeypatch.setattr(apps, "_bundle_id", lambda path: "com.example.tool")
    monkeypatch.setattr(apps, "_objc", _FakeObjC([7]))
    monkeypatch.setattr(apps, "_running_application_class", lambda: 1)
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: running.path)
    monkeypatch.setattr(apps, "_app", lambda handle: running if handle == 7 else None)
    monkeypatch.setattr(apps.time, "sleep", lambda seconds: None)

    assert apps.open("Tool") == running  # the copy that was running before the launch, which macOS activated
    assert fake_run.args == ["open", "-a", asked]
    # The one asked for, when it comes up, is still the one returned: the copy is only a fallback.
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: asked)
    assert apps.open("Tool") == running and apps._find_launched(asked, "com.example.tool") == running
    # A copy that shows up at another path only after the launch isn't what was asked for.
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: "/Applications/Tool.app")
    monkeypatch.setattr(apps, "_running_pids", lambda bundle_id: [])
    with pytest.raises(macos.AppNotFoundError, match="did not show up") as raised:
        apps.open("Tool", timeout=0)
    # A TimeoutError like every other wait, and still the AppNotFoundError it was before.
    assert isinstance(raised.value, macos.errors.AppLaunchTimeoutError) and isinstance(raised.value, TimeoutError)


def test_open_in_the_background_returns_the_copy_running_from_elsewhere_once_the_wait_ends(fake_run, monkeypatch):
    """open -g reopens a running copy without bringing it to the front: it's taken when nothing else came up."""
    from macos import apps

    asked = "/Volumes/Disk/Tool.app"
    running = apps.App("Tool", "com.example.tool", 7, "/Applications/Tool.app")
    fake = _FakeObjC([7], inactive=[7])
    monkeypatch.setattr(apps, "_locate", lambda name: asked)
    monkeypatch.setattr(apps, "_bundle_id", lambda path: "com.example.tool")
    monkeypatch.setattr(apps, "_objc", fake)
    monkeypatch.setattr(apps, "_running_application_class", lambda: 1)
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: running.path)
    monkeypatch.setattr(apps, "_app", lambda handle: running if handle == 7 else None)
    monkeypatch.setattr(apps.time, "sleep", lambda seconds: None)

    # While the wait goes on, the one asked for may still be coming up: the copy in the background isn't taken.
    assert apps._find_launched(asked, "com.example.tool", running_before=[7]) is None
    assert apps.open("Tool", background=True, timeout=0) == running
    assert fake_run.args == ["open", "-g", "-a", asked]


def test_find_launched_skips_an_app_at_the_path_that_has_quit(monkeypatch):
    from macos import apps

    fake = _FakeObjC([5], terminated=[5])
    monkeypatch.setattr(apps, "_objc", fake)
    monkeypatch.setattr(apps, "_handles", lambda include_background: iter([5]))
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: "/Applications/Tool.app")
    monkeypatch.setattr(apps, "_app", lambda handle: pytest.fail("a quit app was taken"))
    assert apps._find_launched("/Applications/Tool.app", None) is None


def test_find_launched_prefers_the_app_asked_for_to_a_copy_listed_before_it(monkeypatch):
    from macos import apps

    asked = "/Volumes/Disk/Tool.app"
    copy = apps.App("Tool", "com.example.tool", 7, "/Applications/Tool.app")
    launched = apps.App("Tool", "com.example.tool", 8, asked)
    monkeypatch.setattr(apps, "_objc", _FakeObjC([7, 8]))  # the copy first, active and running before the launch
    monkeypatch.setattr(apps, "_running_application_class", lambda: 1)
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: copy.path if handle == 7 else asked)
    monkeypatch.setattr(apps, "_app", lambda handle: {7: copy, 8: launched}[handle])
    for in_front in (True, False):
        assert apps._find_launched(asked, "com.example.tool", running_before=[7], in_front=in_front) == launched


def test_open_in_the_background_takes_the_running_copy_after_a_moment_not_at_once(fake_run, monkeypatch):
    from macos import apps

    clock = [100.0]
    running = apps.App("Tool", "com.example.tool", 7, "/Applications/Tool.app")
    monkeypatch.setattr(apps, "_locate", lambda name: "/Volumes/Disk/Tool.app")
    monkeypatch.setattr(apps, "_bundle_id", lambda path: "com.example.tool")
    monkeypatch.setattr(apps, "_objc", _FakeObjC([7], inactive=[7]))
    monkeypatch.setattr(apps, "_running_application_class", lambda: 1)
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: running.path)
    monkeypatch.setattr(apps, "_app", lambda handle: running)
    monkeypatch.setattr(apps.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(apps.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))

    assert apps.open("Tool", background=True) == running
    assert 101.0 <= clock[0] < 101.3  # about a second, not the whole 10-second wait
    # In front, a copy that stays in the background isn't what macOS opened: the wait ends in an error.
    with pytest.raises(macos.AppNotFoundError, match="did not show up"):
        apps.open("Tool", timeout=0.5)


def test_open_doesnt_take_a_copy_that_was_in_front_already_before_the_one_asked_for_can_come_up(fake_run, monkeypatch):
    from macos import apps

    clock = [100.0]
    asked = "/Volumes/Disk/Tool.app"
    running = apps.App("Tool", "com.example.tool", 7, "/Applications/Tool.app")
    launched = apps.App("Tool", "com.example.tool", 8, asked)
    handles = [7]
    monkeypatch.setattr(apps, "_locate", lambda name: asked)
    monkeypatch.setattr(apps, "_bundle_id", lambda path: "com.example.tool")
    monkeypatch.setattr(apps, "_objc", _FakeObjC(handles))  # 7 is active, as the app in front before the call
    monkeypatch.setattr(apps, "_running_application_class", lambda: 1)
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: asked if handle == 8 else running.path)
    monkeypatch.setattr(apps, "_app", lambda handle: launched if handle == 8 else running)
    monkeypatch.setattr(apps.time, "monotonic", lambda: clock[0])

    def sleep(seconds):
        clock[0] += seconds
        if clock[0] >= 100.5 and 8 not in handles:
            handles.append(8)  # the one asked for comes up half a second in

    monkeypatch.setattr(apps.time, "sleep", sleep)
    assert apps.open("Tool") == launched  # not the copy that was already in front


def test_installed_takes_no_number_or_list_for_a_bundle_id_or_a_name(tmp_path, monkeypatch):
    """A hand-made Info.plist with an integer for an ID mustn't stop every other app from being uninstalled."""
    import plistlib

    from macos import apps

    def bundle(name, info):
        path = tmp_path / "Applications" / name
        (path / "Contents").mkdir(parents=True)
        (path / "Contents" / "Info.plist").write_bytes(plistlib.dumps(info))
        return path

    chat = bundle("Chat.app", {"CFBundleName": "Chat", "CFBundleIdentifier": "com.example.Chat"})
    odd = bundle("Odd.app", {"CFBundleDisplayName": ["Odd"], "CFBundleName": "", "CFBundleIdentifier": 12345})
    weird = apps._installed_app(str(odd))
    assert weird is not None and (weird.name, weird.bundle_id) == ("Odd", None)
    assert apps._installed_app(str(bundle("Empty.app", {"CFBundleIdentifier": ""}))).bundle_id is None

    home = tmp_path / "home"
    (home / "Library" / "Caches" / "com.example.Chat").mkdir(parents=True)
    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(apps, "_locate", lambda name: str(chat))
    monkeypatch.setattr(apps, "_installed", lambda: [apps._installed_app(str(chat)), weird])
    monkeypatch.setattr(apps.Path, "home", lambda: home)
    assert apps.uninstall("Chat", dry_run=True) == [chat, home / "Library/Caches/com.example.Chat"]


def test_a_translocated_app_is_known_by_the_path_it_was_opened_from(fake_run, monkeypatch):
    """A downloaded app runs from a random AppTranslocation copy: open, get and uninstall must still see it."""
    import contextlib
    import types

    from macos import apps

    asked = "/Users/me/Downloads/Tool.app"
    copy = "/private/var/folders/x/AppTranslocation/0A1B/d/Tool.app"
    released = []
    security = types.SimpleNamespace(SecTranslocateCreateOriginalPathForURL=lambda url, error: 99)
    monkeypatch.setattr(apps, "_translocation", lambda: security)
    monkeypatch.setattr(
        apps,
        "_cf",
        types.SimpleNamespace(
            file_url=lambda path, directory=False: 5, owned=contextlib.nullcontext, release=released.append
        ),
    )
    monkeypatch.setattr(apps, "_app_path", lambda url: asked if url == 99 else None)
    monkeypatch.setattr(apps.os.path, "realpath", lambda path: path)
    assert apps._real_bundle_path(copy) == asked
    assert apps._real_bundle_path("/Applications/Tool.app") == "/Applications/Tool.app"  # not asked about
    monkeypatch.setattr(apps, "_translocation", lambda: None)  # a macOS that can't say
    assert apps._real_bundle_path(copy) == copy
    monkeypatch.setattr(apps, "_translocation", lambda: security)

    running = apps.App("Tool", "com.example.tool", 8, copy)
    monkeypatch.setattr(apps, "running", lambda include_background=False: [running])
    assert apps.get(asked) == running and apps.get("/Applications/Tool.app") is None
    assert apps.get(running.path) == running  # the copy's own path, as App.path hands it back

    # open(): the new process at the copy's path is the one launched, not a copy that ran before.
    monkeypatch.setattr(apps, "_locate", lambda name: asked)
    monkeypatch.setattr(apps, "_bundle_id", lambda path: "com.example.tool")
    monkeypatch.setattr(apps, "_running_pids", lambda bundle_id: [])
    monkeypatch.setattr(apps, "_objc", _FakeObjC([8]))
    monkeypatch.setattr(apps, "_running_application_class", lambda: 1)
    monkeypatch.setattr(apps, "_bundle_path", lambda handle: apps._real_bundle_path(copy))
    monkeypatch.setattr(apps, "_app", lambda handle: running)
    monkeypatch.setattr(apps.time, "sleep", lambda seconds: None)
    assert apps.open(asked, timeout=0) == running
    monkeypatch.setattr(apps, "_locate", lambda name: copy)
    assert apps.open(copy, timeout=0) == running  # opened by the copy's path


def test_uninstall_refuses_an_app_running_from_a_translocated_copy(tmp_path, monkeypatch):
    import plistlib

    from macos import apps

    bundle = tmp_path / "Downloads" / "Tool.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": "com.example.tool"}))
    copy = "/private/var/folders/x/AppTranslocation/0A1B/d/Tool.app"
    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(apps, "_locate", lambda name: str(bundle))
    monkeypatch.setattr(apps, "_installed", lambda: [])
    monkeypatch.setattr(apps.Path, "home", lambda: tmp_path / "home")
    monkeypatch.setattr(apps, "running", lambda include_background=False: [apps.App("Tool", None, 8, copy)])
    monkeypatch.setattr(apps, "_real_bundle_path", lambda path: str(bundle) if path == copy else path)
    monkeypatch.setattr(apps.finder, "trash", lambda path: pytest.fail("a running app was moved"))
    with pytest.raises(macos.MacOSError, match="is running"):
        apps.uninstall("Tool")


def test_an_app_whose_pid_went_to_another_app_is_no_longer_running(monkeypatch):
    """Once it has quit, its pid may go to another app: that one mustn't be force-quit or hidden in its place."""
    from macos import apps

    class Fake(_FakeObjC):
        dates = {7: 100.0}

        def send(self, receiver, selector, *args, **kwargs):
            if selector == "launchDate":
                self.sent.append(selector)
                return ("date", receiver) if receiver in self.dates else None
            if selector == "timeIntervalSinceReferenceDate":
                return self.dates[receiver[1]]
            return super().send(receiver, selector, *args, **kwargs)

    fake = Fake([7])
    monkeypatch.setattr(apps, "_objc", fake)
    monkeypatch.setattr(apps, "_handle", lambda pid: pid)
    app = apps.App("TextEdit", "com.apple.TextEdit", 7, "/Applications/TextEdit.app", _launched=100.0)
    assert app.is_running and app.hide()
    assert app == apps.App("TextEdit", "com.apple.TextEdit", 7, "/Applications/TextEdit.app")  # not compared
    assert "_launched" not in repr(app)

    Fake.dates = {7: 250.0}  # pid 7 is another process now
    assert not app.is_running
    for call in (app.hide, lambda: app.quit(force=True)):
        with pytest.raises(macos.AppNotFoundError, match="no longer running"):
            call()
    assert "forceTerminate" not in fake.sent and "hide" in fake.sent  # hide only from the first, live call
    Fake.dates = {}  # nor a process macOS has no date for
    assert not app.is_running
    assert apps.App("Tool", None, 7, None).is_running  # one made by hand has no date to check


def test_activate_looks_the_app_up_in_an_autorelease_pool(fake_run, monkeypatch):
    import contextlib

    from macos import apps

    pools = []

    class Fake(_FakeObjC):
        def autorelease_pool(self):
            pools.append(len(lookups))
            return contextlib.nullcontext()

    lookups = []
    monkeypatch.setattr(apps, "_objc", Fake([7]))
    monkeypatch.setattr(apps, "_handle", lambda pid: lookups.append(pid) or pid)
    assert apps.App("Tool", None, 7, "/Applications/Tool.app").activate(timeout=0)
    assert pools[0] == 0 and fake_run.args == ["open", "-a", "/Applications/Tool.app"]  # a pool before the lookup


@pytest.mark.parametrize("timeout", [None, float("inf")])
def test_setting_a_default_app_can_wait_as_long_as_it_takes(monkeypatch, timeout):
    import threading

    from macos import apps

    class Lock:
        def __init__(self):
            self.lock, self.timeouts = threading.Lock(), []

        def acquire(self, *args, **kwargs):
            self.timeouts.append(kwargs.get("timeout"))
            return self.lock.acquire(*args, **kwargs)

        def release(self):
            self.lock.release()

    lock, waits = Lock(), []
    monkeypatch.setattr(apps, "_default_call", lock)
    monkeypatch.setattr(apps, "_default_handler", lambda generation: 1)
    monkeypatch.setattr(apps, "framework", lambda name: None)
    monkeypatch.setattr(apps._objc, "cls", lambda name: 1)
    monkeypatch.setattr(apps._objc, "nsstring", lambda text: 1)
    monkeypatch.setattr(apps._objc, "file_url", lambda path: 1)
    monkeypatch.setattr(apps._objc, "send", lambda receiver, selector, *args, **kwargs: 1)

    def run_until(done, wait):
        waits.append(wait)
        apps._default_answer(apps._default_generation[0], None)  # confirmed
        return done()

    monkeypatch.setattr(apps._objc, "run_until", run_until)
    apps._set_default_with_workspace(1, "/Applications/Tool.app", "public.plain-text", "Tool", "txt", timeout)
    assert lock.timeouts == [None] and waits == [float("inf")]  # no OverflowError, no TypeError


@pytest.mark.parametrize("timeout", [float("nan"), -1])
def test_setting_a_default_app_refuses_a_timeout_that_isnt_one(monkeypatch, timeout):
    from macos import apps

    monkeypatch.setattr(apps, "_locate", lambda name: pytest.fail("looked the app up"))
    with pytest.raises(ValueError, match="timeout"):
        apps.set_default_for("txt", "TextEdit", timeout=timeout)


def test_uninstall_refuses_an_app_on_the_system_volume(tmp_path, monkeypatch):
    """Before macOS 13, Safari is a real bundle in /Applications, on the sealed, read-only system volume."""
    import os
    import plistlib
    import types

    from macos import apps

    bundle = tmp_path / "Applications" / "Safari.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents" / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleName": "Safari", "CFBundleIdentifier": "com.apple.Safari"})
    )
    devices = {"/": 1, str(bundle): 1}
    flags = {"/": os.ST_RDONLY, str(bundle): os.ST_RDONLY}
    # apps.os is os itself: answer for "/" and the bundle only, so pytest's own calls (a failure's report) still work.
    real_stat, real_statvfs = os.stat, os.statvfs

    def stat(path, *args, **kwargs):
        if str(path) in devices:
            return types.SimpleNamespace(st_dev=devices[str(path)])
        return real_stat(path, *args, **kwargs)

    def statvfs(path):
        if str(path) in flags:
            return types.SimpleNamespace(f_flag=flags[str(path)])
        return real_statvfs(path)

    monkeypatch.setattr(apps.os, "stat", stat)
    monkeypatch.setattr(apps.os, "statvfs", statvfs)
    monkeypatch.setattr(apps, "require_macos", lambda: None)
    monkeypatch.setattr(apps, "_locate", lambda name: str(bundle))
    monkeypatch.setattr(apps, "_installed", lambda: pytest.fail("listed the other apps"))
    with pytest.raises(macos.MacOSError, match="comes with macOS"):
        apps.uninstall("Safari", dry_run=True)

    assert apps._on_system_volume(str(bundle))
    devices[str(bundle)] = 2  # the Data volume, where /Applications's own apps are
    assert not apps._on_system_volume(str(bundle))
    devices[str(bundle)] = 1
    flags[str(bundle)] = 0  # / writable: older macOS
    assert not apps._on_system_volume(str(bundle))


def test_get_returns_the_first_of_the_running_apps_its_name_matches(monkeypatch):
    from macos import apps

    first = apps.App(name="Tool", bundle_id="com.example.tool", pid=1, path="/Applications/Tool.app")
    copy = apps.App(name="Tool", bundle_id="com.example.tool", pid=2, path="/Users/me/Tool.app")
    other = apps.App(name="Other", bundle_id="com.example.other", pid=3, path="/Applications/Other.app")
    monkeypatch.setattr(apps, "running", lambda include_background=False: [first, other, copy])
    monkeypatch.setattr(apps, "_real_bundle_path", lambda path: path.replace("/Users/me", "/Applications"))

    assert list(apps._matches("tool")) == [first, copy] and apps.get("tool") == first
    assert list(apps._matches("com.example.other")) == [other] == [apps.get("Other.app")]
    # Paths: both sides go through _real_bundle_path, so the copy's path finds both copies.
    assert list(apps._matches("/Users/me/Tool.app")) == [first, copy]
    assert list(apps._matches("Missing")) == [] and apps.get("Missing") is None
