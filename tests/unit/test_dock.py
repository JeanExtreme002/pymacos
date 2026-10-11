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
    sent = []

    class ObjC:
        id = object
        BOOL = bool

        def send(self, receiver, selector, *args, **kwargs):
            sent.append(selector)
            return {"isTerminated": False, "processIdentifier": 321}.get(selector, 1)

        def nsarray(self, obj):
            return [11]

        def nsstring(self, text):
            return text

        def autorelease_pool(self):
            import contextlib

            return contextlib.nullcontext()

    monkeypatch.setattr(dock, "_objc", ObjC())
    monkeypatch.setattr(dock._apps, "_running_application_class", lambda: 1)
    assert dock._pid() == 321
    assert sent[0] == "runningApplicationsWithBundleIdentifier:"  # one call, not a scan of every process


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

    with pytest.raises(macos.MacOSError, match="didn't start again"):
        dock.restart()


def test_dock_add_app_index_skips_spacers(dock_settings):
    store, _, _ = dock_settings
    store["persistent-apps"].insert(0, {"tile-data": {}, "tile-type": "spacer-tile"})

    macos.dock.add_app("Code", index=1)  # after Safari, the first app
    assert [tile.get("tile-type") for tile in store["persistent-apps"]] == ["spacer-tile", "file-tile", "file-tile"]
    assert [entry.name for entry in macos.dock.apps()] == ["Safari", "Code"]


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
