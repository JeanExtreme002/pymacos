"""Unit tests for :mod:`macos.dock`. They run on any platform."""

import pytest

import macos
from macos import dock


@pytest.fixture
def dock_settings(monkeypatch, tmp_path):
    """The Dock's preferences in a dict, and the restarts counted."""
    store = {
        "persistent-apps": [
            {"tile-data": {"file-data": {"_CFURLString": "file:///Applications/Safari.app/", "_CFURLStringType": 15},
                           "file-label": "Safari", "bundle-identifier": "com.apple.Safari"}, "tile-type": "file-tile"},
        ],
        "tilesize": 48.0,
    }  # fmt: skip
    restarts = []
    monkeypatch.setattr(dock.defaults, "read", lambda domain, key=None, default=None: store.get(key, default))
    monkeypatch.setattr(dock.defaults, "write", lambda domain, key, value: store.__setitem__(key, value))
    monkeypatch.setattr(dock, "restart", lambda: restarts.append(1))
    monkeypatch.setattr(dock.os.path, "realpath", lambda path: path)
    app = tmp_path / "Code.app"
    app.mkdir()
    monkeypatch.setattr(dock._apps, "_locate", lambda name: str(app))
    monkeypatch.setattr(dock._apps, "_bundle_id", lambda path: "com.example.code")
    return store, restarts, app


def test_dock_remove_app_takes_whatever_add_app_took(dock_settings):
    store, restarts, app = dock_settings

    # The same spellings add_app() accepts: the name with or without .app, the bundle ID, the path.
    for spelling in ("Safari.app", "safari.APP", "com.apple.Safari", "/Applications/Safari.app", "/Applications/Safari"):
        store["persistent-apps"] = [
            {"tile-data": {"file-data": {"_CFURLString": "file:///Applications/Safari.app/", "_CFURLStringType": 15},
                           "file-label": "Safari", "bundle-identifier": "com.apple.Safari"}, "tile-type": "file-tile"},
        ]  # fmt: skip
        assert macos.dock.remove_app(spelling) is True, spelling
        assert store["persistent-apps"] == []
    added = macos.dock.add_app("Code.app")
    assert macos.dock.remove_app("Code.app") is True and added.path == app
    assert macos.dock.remove_app("Code.app") is False
    # A bundle ID that ends in ".app" is a bundle ID: nothing is cut off it.
    store["persistent-apps"] = [
        {"tile-data": {"file-data": {"_CFURLString": "file:///Applications/Tool.app/", "_CFURLStringType": 15},
                       "file-label": "Tool", "bundle-identifier": "com.vendor.tool.app"}, "tile-type": "file-tile"},
    ]  # fmt: skip
    assert macos.dock.remove_app("com.vendor.tool.app") is True and store["persistent-apps"] == []


def test_dock_restart_tolerates_a_dock_that_is_not_running(monkeypatch, commands):
    pids = [None, None, 7]
    monkeypatch.setattr(dock, "_pid", lambda: pids.pop(0) if len(pids) > 1 else pids[0])
    monkeypatch.setattr(dock.time, "sleep", lambda seconds: None)
    commands.answers["-KILL"] = (1, "", "No matching processes belonging to you were found")

    dock.restart()  # killed a moment ago, not back yet: it reads the settings when it starts
    assert commands.calls[-1] == ["killall", "-KILL", "Dock"]
    commands.answers["-KILL"] = (1, "", "Operation not permitted")
    with pytest.raises(macos.CommandError, match="not permitted"):
        dock.restart()


def test_dock_pid_asks_for_the_dock_alone(monkeypatch):
    asked = []

    class ObjC:
        def send(self, receiver, selector, *args, **kwargs):
            assert (receiver, selector) == (11, "processIdentifier")
            return 321

        def autorelease_pool(self):
            import contextlib

            return contextlib.nullcontext()

    monkeypatch.setattr(dock, "_objc", ObjC())
    # The apps module's helper asks LaunchServices about that one bundle ID, not about every process.
    monkeypatch.setattr(dock._apps, "_handles_with_bundle_id", lambda bundle_id: asked.append(bundle_id) or [11])
    assert dock._pid() == 321 and asked == ["com.apple.dock"]
    monkeypatch.setattr(dock._apps, "_handles_with_bundle_id", lambda bundle_id: [])
    assert dock._pid() is None  # killed a moment ago, not back yet


def test_dock_settings(dock_settings):
    store, restarts, _ = dock_settings

    assert (macos.dock.size(), macos.dock.position(), macos.dock.autohide()) == (48, "bottom", False)
    macos.dock.set_autohide(True)
    macos.dock.set_size(64)
    macos.dock.set_position("left")
    assert (store["autohide"], store["tilesize"], store["orientation"]) == (True, 64.0, "left")
    assert len(restarts) == 3
    with pytest.raises(ValueError, match="16 to 128"):
        macos.dock.set_size(200)
    with pytest.raises(ValueError, match="'left', 'bottom' or 'right'"):
        macos.dock.set_position("top")


def test_dock_apps(dock_settings):
    store, restarts, app = dock_settings

    assert [(entry.name, entry.bundle_id) for entry in macos.dock.apps()] == [("Safari", "com.apple.Safari")]
    added = macos.dock.add_app("Code", index=0)
    assert (added.name, added.bundle_id, added.path) == ("Code", "com.example.code", app)
    assert [entry.name for entry in macos.dock.apps()] == ["Code", "Safari"]
    assert store["persistent-apps"][0]["tile-data"]["file-data"]["_CFURLString"].startswith("file://")
    macos.dock.add_app("Code")  # already there: not twice
    assert [entry.name for entry in macos.dock.apps()] == ["Code", "Safari"] and len(restarts) == 1
    assert macos.dock.remove_app("safari") is True and macos.dock.remove_app("Safari") is False
    assert [entry.name for entry in macos.dock.apps()] == ["Code"]


def test_dock_apps_leave_out_spacers(dock_settings):
    store, _, _ = dock_settings
    store["persistent-apps"].append({"tile-data": {}, "tile-type": "spacer-tile"})
    store["persistent-apps"].append({"tile-data": {}, "tile-type": "small-spacer-tile"})

    assert [entry.name for entry in macos.dock.apps()] == ["Safari"]


def test_dock_restart_fails_when_no_dock_comes_back(monkeypatch, fake_run):
    clock = {"now": 0.0}
    monkeypatch.setattr(dock, "_pid", lambda: 42)  # the same Dock, never replaced
    monkeypatch.setattr(dock.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(dock.time, "sleep", lambda seconds: clock.update(now=clock["now"] + seconds))

    with pytest.raises(macos.WaitTimeoutError, match="didn't start again"):
        dock.restart()


def test_dock_add_app_index_skips_spacers(dock_settings):
    store, _, _ = dock_settings
    store["persistent-apps"].insert(0, {"tile-data": {}, "tile-type": "spacer-tile"})

    macos.dock.add_app("Code", index=1)  # after Safari, the first app
    assert [tile.get("tile-type") for tile in store["persistent-apps"]] == ["spacer-tile", "file-tile", "file-tile"]
    assert [entry.name for entry in macos.dock.apps()] == ["Safari", "Code"]


def test_dock_add_app_replaces_a_tile_of_another_kind_at_that_path(dock_settings):
    store, restarts, app = dock_settings
    # A folder tile pointing at the app's path: adding the app takes its place, it isn't there twice.
    store["persistent-apps"] = [
        {"tile-data": {"file-data": {"_CFURLString": "file://{}/".format(app), "_CFURLStringType": 15}},
         "tile-type": "directory-tile"},
    ] + store["persistent-apps"]  # fmt: skip
    store["persistent-apps"].insert(1, {"tile-data": {}, "tile-type": "spacer-tile"})  # folder, spacer, Safari
    added = macos.dock.add_app("Code")
    tiles = store["persistent-apps"]
    assert added.path == app and len(tiles) == 3 and tiles[0]["tile-type"] == "file-tile"  # the folder's exact slot
    assert [tile["tile-type"] for tile in tiles] == ["file-tile", "spacer-tile", "file-tile"]
    assert [tile["tile-data"].get("file-label") for tile in tiles] == ["Code", None, "Safari"]
    assert macos.dock.remove_app("Code") is True and len(store["persistent-apps"]) == 2
    with pytest.raises(ValueError, match="is an app"):
        macos.dock.add_folder(app)  # a bundle is a folder to the file system, not to the Dock
    # With an index asked for, the stray goes and the index counts the apps, as always.
    store["persistent-apps"] = [
        {"tile-data": {}, "tile-type": "spacer-tile"},
        {"tile-data": {"file-data": {"_CFURLString": "file://{}/".format(app), "_CFURLStringType": 15}},
         "tile-type": "directory-tile"},
    ] + store["persistent-apps"]  # fmt: skip
    macos.dock.add_app("Code", index=0)  # the spacer left by remove_app() above is still there
    assert [tile["tile-data"].get("file-label") for tile in store["persistent-apps"]] == [None, None, "Code", "Safari"]
    # Kept as an app already, with a stray folder tile beside it and one on the right side: the strays go.
    store["persistent-apps"].append(
        {"tile-data": {"file-data": {"_CFURLString": "file://{}/".format(app), "_CFURLStringType": 15}},
         "tile-type": "directory-tile"}
    )  # fmt: skip
    store["persistent-others"] = [
        {"tile-data": {"file-data": {"_CFURLString": "file://{}/".format(app), "_CFURLStringType": 15}},
         "tile-type": "directory-tile"},
        {"tile-data": {"file-data": {"_CFURLString": "file:///Users/me/Downloads/", "_CFURLStringType": 15}},
         "tile-type": "directory-tile"},
    ]  # fmt: skip
    before = len(restarts)
    assert macos.dock.add_app("Code").path == app
    assert [tile["tile-data"].get("file-label") for tile in store["persistent-apps"]] == [None, None, "Code", "Safari"]
    assert len(store["persistent-others"]) == 1 and len(restarts) == before + 1
    assert macos.dock.add_app("Code").path == app and len(restarts) == before + 1  # nothing to change: no restart


def test_dock_add_app_with_a_stray_right_before_another_app(dock_settings):
    store, _, app = dock_settings
    # The folder tile goes, and the app after it (Safari) isn't taken for the one asked for.
    store["persistent-apps"].insert(
        0,
        {"tile-data": {"file-data": {"_CFURLString": "file://{}/".format(app), "_CFURLStringType": 15}},
         "tile-type": "directory-tile"},
    )  # fmt: skip
    added = macos.dock.add_app("Code")
    assert added.path == app and added.bundle_id == "com.example.code"
    assert [tile["tile-data"].get("file-label") for tile in store["persistent-apps"]] == ["Code", "Safari"]


def test_dock_remove_app_leaves_spacers_and_refuses_an_empty_name(dock_settings):
    store, restarts, _ = dock_settings
    spacer = {"tile-data": {}, "tile-type": "spacer-tile"}
    unlabelled = {"tile-data": {}, "tile-type": "file-tile"}  # no label, no bundle ID: matched "" before
    store["persistent-apps"] += [spacer, unlabelled]

    for blank in ("", "   "):
        with pytest.raises(ValueError, match="needs an app"):
            macos.dock.remove_app(blank)
    assert macos.dock.remove_app("Safari") is True
    assert store["persistent-apps"] == [spacer, unlabelled] and len(restarts) == 1


def test_dock_numbers_tolerate_hand_edited_values(dock_settings):
    store, _, _ = dock_settings
    store.update({"tilesize": "big", "autohide-delay": "soon", "magnification": True, "largesize": float("nan"),
                  "autohide-time-modifier": ["x"], "wvous-tl-corner": "x", "wvous-tl-modifier": {}})  # fmt: skip
    assert macos.dock.size() == 64 and macos.dock.autohide_delay() == 0.5 and macos.dock.magnification() == 128
    assert macos.dock.autohide_duration() is None
    assert macos.dock.hot_corners()["top_left"] is None and macos.dock.hot_corner_modifiers()["top_left"] is None
    store.update({"tilesize": "48", "autohide-delay": 0})  # a number written as text still reads
    assert macos.dock.size() == 48 and macos.dock.autohide_delay() == 0.0


def test_dock_tiles_tolerate_hand_edited_values(dock_settings):
    store, restarts, app = dock_settings
    # The lists of tiles replaced by something else, or holding something that isn't a tile: not a crash.
    store["persistent-apps"] = "Safari"
    store["persistent-others"] = {"tile-type": "directory-tile"}
    with pytest.warns(RuntimeWarning, match="isn't a list of tiles"):
        assert macos.dock.apps() == [] and macos.dock.folders() == []
    with pytest.warns(RuntimeWarning, match="isn't a list of tiles"):
        assert macos.dock.remove_app("Safari") is False and macos.dock.remove_spacers() == 0 and restarts == []
        added = macos.dock.add_app("Code")  # written back as a proper list
    assert added.path == app and [entry.name for entry in macos.dock.apps()] == ["Code"]
    store["persistent-apps"] = [
        "Safari",
        42,
        {"tile-data": {"file-data": {"_CFURLString": "file:///Applications/Safari.app/", "_CFURLStringType": 15},
                       "file-label": "Safari", "bundle-identifier": "com.apple.Safari"}, "tile-type": "file-tile"},
    ]  # fmt: skip
    with pytest.warns(RuntimeWarning, match="2 of the Dock's persistent-apps entries aren't tiles") as reported:
        assert [entry.name for entry in macos.dock.apps()] == ["Safari"]
    assert reported[0].filename == __file__  # it points at the call to apps(), not inside the package
    # A folder's view, sort and icon edited into text, a list, a number out of range: the defaults, as for the Dock's numbers.
    store["persistent-others"] = [
        {"tile-data": {"file-data": {"_CFURLString": "file:///Users/me/Downloads/", "_CFURLStringType": 15},
                       "file-label": "Downloads", "showas": "fan", "arrangement": [2], "displayas": 7},
         "tile-type": "directory-tile"},
        {"tile-data": {"file-data": {"_CFURLString": "file:///Users/me/Projects/", "_CFURLStringType": 15},
                       "file-label": "Projects", "showas": "2", "arrangement": 1.0, "displayas": "1"},
         "tile-type": "directory-tile"},
    ]  # fmt: skip
    folders = macos.dock.folders()
    assert [(folder.view, folder.sort, folder.display) for folder in folders] == [
        ("automatic", "name", "stack"),
        ("grid", "name", "folder"),  # numbers written as text still read
    ]


def test_dock_tiles_with_hand_edited_contents_read_as_no_app(dock_settings):
    store, restarts, app = dock_settings
    safari = store["persistent-apps"][0]
    # Dictionaries, so tiles, but what they hold was edited into something else: skipped, and kept as they are.
    odd = [
        {"tile-data": "x", "tile-type": "file-tile"},
        {"tile-data": {"file-data": []}, "tile-type": "file-tile"},
        {"tile-data": {"file-data": {"_CFURLString": 5}}, "tile-type": "file-tile"},
        {"tile-data": {"file-data": {"_CFURLString": "file:///a%00b/"}}, "tile-type": "file-tile"},
        {"tile-data": {"file-data": {"_CFURLString": "file://"}}, "tile-type": "file-tile"},
    ]
    store["persistent-apps"] = [*odd, safari]
    store["persistent-others"] = [{"tile-data": "x", "tile-type": "directory-tile"}]
    assert [entry.name for entry in macos.dock.apps()] == ["Safari"]
    assert [(folder.name, folder.path, folder.view) for folder in macos.dock.folders()] == [("", None, "automatic")]
    assert macos.dock.remove_app("Safari") is True and store["persistent-apps"] == odd
    macos.dock.add_spacer()
    assert macos.dock.add_app("Code").path == app and store["persistent-apps"][: len(odd)] == odd
    assert len(restarts) == 3


def test_dock_folder_of_the_whole_disk_is_the_root_not_the_current_folder(dock_settings):
    store, _, _ = dock_settings
    for url in ("file:///", "file:////"):  # as the Dock writes the disk, and as add_folder("/") would
        store["persistent-others"] = [
            {"tile-data": {"file-data": {"_CFURLString": url, "_CFURLStringType": 15}, "file-label": "Macintosh HD"},
             "tile-type": "directory-tile"},
        ]  # fmt: skip
        assert [folder.path for folder in macos.dock.folders()] == [macos.dock.Path("/")], url


def test_dock_tiles_keep_file_urls_as_the_dock_writes_them(dock_settings):
    store, _, app = dock_settings
    folder = app.parent / "My Projects"
    folder.mkdir()
    kept = macos.dock.add_folder(folder)
    url = store["persistent-others"][0]["tile-data"]["file-data"]["_CFURLString"]
    assert url == "file://{}/My%20Projects/".format(app.parent) and kept.path == folder
    assert [entry.path for entry in macos.dock.folders()] == [folder]  # read back through the same escapes


def test_dock_add_app_refuses_a_folder_that_is_not_an_app(dock_settings, monkeypatch, tmp_path):
    store, restarts, app = dock_settings
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr(dock._apps, "_locate", lambda name: str(downloads))
    folder = {"tile-data": {"file-data": {"_CFURLString": "file://{}/".format(downloads), "_CFURLStringType": 15}},
              "tile-type": "directory-tile"}  # fmt: skip
    store["persistent-others"] = [folder]
    apps_before = list(store["persistent-apps"])
    with pytest.raises(macos.AppNotFoundError, match="add_folder"):
        macos.dock.add_app(str(downloads))
    # Nothing touched: the Dock folder at that path stays, and no tile joins the apps.
    assert store["persistent-others"] == [folder] and store["persistent-apps"] == apps_before and restarts == []
    # A bundle without the .app suffix is still an app, by what its Info.plist says.
    bundle = tmp_path / "Tool"
    (bundle / "Contents").mkdir(parents=True)
    with open(bundle / "Contents" / "Info.plist", "wb") as file:
        dock.plistlib.dump({"CFBundlePackageType": "APPL"}, file)
    monkeypatch.setattr(dock._apps, "_locate", lambda name: str(bundle))
    assert macos.dock.add_app(str(bundle)).path == bundle


def test_dock_add_and_remove_app_take_a_path(dock_settings, monkeypatch, tmp_path):
    store, restarts, app = dock_settings
    located = []
    monkeypatch.setattr(dock._apps, "_locate", lambda name: located.append(name) or str(app))
    assert macos.dock.add_app(app).path == app and located == [str(app)]
    # What apps() returns goes back in as it is.
    assert macos.dock.remove_app(macos.dock.apps()[-1].path) is True
    assert [entry.name for entry in macos.dock.apps()] == ["Safari"]
    # A relative Path is a path, not the name of an app.
    monkeypatch.chdir(tmp_path)
    macos.dock.add_app(dock.Path("Code.app"))
    assert located[-1] == str(app) and dock._apps._is_path(located[-1])
    assert macos.dock.remove_app(dock.Path("Code.app")) is True
    with pytest.raises(TypeError, match="name, bundle ID or path"):
        macos.dock.add_app(42)  # type: ignore[arg-type]

    class BytesPath:
        def __fspath__(self):
            return b"/Applications/Safari.app"

    with pytest.raises(TypeError, match="as text"):
        macos.dock.remove_app(BytesPath())  # type: ignore[arg-type]


def test_dock_negative_index_counts_from_the_right(dock_settings, monkeypatch, tmp_path):
    store, _, app = dock_settings
    mail = {"tile-data": {"file-data": {"_CFURLString": "file:///Applications/Mail.app/", "_CFURLStringType": 15},
                          "file-label": "Mail"}, "tile-type": "file-tile"}  # fmt: skip
    store["persistent-apps"].append(mail)  # Safari, Mail
    macos.dock.add_spacer(index=-1)
    assert [tile["tile-data"].get("file-label") for tile in store["persistent-apps"]] == ["Safari", None, "Mail"]
    macos.dock.add_app("Code", index=-1)  # the spacer isn't counted: before Mail, the last app
    assert [entry.name for entry in macos.dock.apps()] == ["Safari", "Code", "Mail"]
    assert store["persistent-apps"][2]["tile-data"]["file-label"] == "Code"
    macos.dock.add_spacer(index=-100, small=True)  # far past the first: first
    assert store["persistent-apps"][0]["tile-type"] == "small-spacer-tile"
    store["persistent-apps"] = []
    macos.dock.add_spacer(index=-1)  # no apps at all: at the end
    assert [tile["tile-type"] for tile in store["persistent-apps"]] == ["spacer-tile"]


def test_dock_autohide_timings_refuse_numbers_that_are_not_finite(dock_settings):
    store, restarts, _ = dock_settings
    for seconds in (float("nan"), float("inf"), -1.0):
        with pytest.raises(ValueError, match="finite"):
            macos.dock.set_autohide_delay(seconds)
        with pytest.raises(ValueError, match="finite"):
            macos.dock.set_autohide_duration(seconds)
    assert "autohide-delay" not in store and "autohide-time-modifier" not in store and restarts == []
    macos.dock.set_autohide_delay(0)
    assert store["autohide-delay"] == 0.0


def test_dock_folders_refuse_an_empty_path(dock_settings):
    store, restarts, _ = dock_settings
    with pytest.raises(ValueError, match="needs a folder"):
        macos.dock.add_folder("")
    with pytest.raises(ValueError, match="needs a folder"):
        macos.dock.remove_folder("")
    assert "persistent-others" not in store and restarts == []


def test_dock_minimize_effect_reads_and_writes_suck(dock_settings):
    store, _, _ = dock_settings
    store["mineffect"] = "suck"  # hidden from System Settings, but the Dock takes it
    assert macos.dock.minimize_effect() == "suck"
    macos.dock.set_minimize_effect("scale")
    macos.dock.set_minimize_effect("suck")
    assert store["mineffect"] == "suck"
    store["mineffect"] = "wobbly"
    assert macos.dock.minimize_effect() == "genie"
    with pytest.raises(ValueError, match="'genie', 'scale', 'suck'"):
        macos.dock.set_minimize_effect("wobbly")


def test_dock_switches_read_text_written_without_bool_as_macos_does(dock_settings):
    store, _, _ = dock_settings
    switches = {"autohide": dock.autohide, "show-recents": dock.show_recents,
                "show-process-indicators": dock.show_indicators, "minimize-to-application": dock.minimize_to_app,
                "mru-spaces": dock.auto_rearrange_spaces, "showhidden": dock.dim_hidden_apps,
                "static-only": dock.only_open_apps, "launchanim": dock.launch_animation,
                "expose-group-apps": dock.group_windows_by_app,
                "AppleSpacesSwitchOnActivate": dock.switch_to_space_with_app}  # fmt: skip
    for off in ("NO", "false", "0"):  # `defaults write com.apple.dock autohide NO` stores the text
        store.update(dict.fromkeys(switches, off), magnification=off, largesize=96.0, **{"spans-displays": off})
        assert [read() for read in switches.values()] == [False] * len(switches), off
        assert dock.magnification() is None and dock.separate_spaces_per_display() is True
    store.update(dict.fromkeys(switches, "YES"), magnification="true", **{"spans-displays": "1"})
    assert all(read() for read in switches.values())
    assert dock.magnification() == 96 and dock.separate_spaces_per_display() is False
    store.update(dict.fromkeys(switches, "maybe"))  # unreadable text reads as the default
    assert (dock.autohide(), dock.show_recents(), dock.launch_animation()) == (False, True, True)
