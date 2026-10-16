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

    with pytest.raises(macos.AppNotFoundError, match="has no app at its top"):
        apps.install_from_dmg(tmp_path / "Tool.dmg", destination=tmp_path / "Applications")
    assert copied == []

    # Beside a real app, the link is left out: no warning about several apps, and app= can't pick it.
    (volume / "Real.app" / "Contents").mkdir(parents=True)
    with pytest.raises(macos.AppNotFoundError):
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
    monkeypatch.setattr(apps, "installed", lambda: [apps._installed_app(str(bundle))])
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
    monkeypatch.setattr(apps, "installed", lambda: [apps._installed_app(str(bundle))])
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

    with pytest.warns(RuntimeWarning, match="Spotlight couldn't be asked"):
        assert [app.name for app in apps.installed()] == ["Tool"]
    assert queries and queries[0]["timeout"] == apps._SPOTLIGHT_TIMEOUT > 0


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

    def __init__(self, handles, terminated=()):
        self.handles, self.terminated, self.sent = handles, set(terminated), []
        self.id = object

    def send(self, receiver, selector, *args, **kwargs):
        self.sent.append(selector)
        if selector == "isTerminated":
            return receiver in self.terminated
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
    with pytest.raises(macos.AppNotFoundError, match="did not show up"):
        apps.open("Tool", timeout=0)
