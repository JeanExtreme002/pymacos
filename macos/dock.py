# -*- coding: utf-8 -*-

"""
Configure the Dock: hide it, size and place it, and choose the apps kept in it.

::

    macos.dock.set_autohide(True)
    macos.dock.set_size(48)                      # icons of 48 points
    macos.dock.set_position("left")
    [app.name for app in macos.dock.apps()]      # ['Safari', 'Mail', 'Music', ...]
    macos.dock.add_app("Visual Studio Code")
    macos.dock.remove_app("Podcasts")

Each change restarts the Dock to apply it: it disappears for a second. No
permission is needed.
"""

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote, unquote, urlparse

from . import apps as _apps, defaults
from ._system import require_macos, restart_later, run as _run
from .errors import AppNotFoundError, MacOSError

__all__ = [
    "DockApp",
    "autohide",
    "set_autohide",
    "size",
    "set_size",
    "position",
    "set_position",
    "apps",
    "add_app",
    "remove_app",
    "restart",
    "HOT_CORNER_ACTIONS",
    "hot_corners",
    "set_hot_corner",
    "autohide_delay",
    "set_autohide_delay",
    "magnification",
    "set_magnification",
    "show_recents",
    "set_show_recents",
    "minimize_effect",
    "set_minimize_effect",
    "show_indicators",
    "set_show_indicators",
    "minimize_to_app",
    "set_minimize_to_app",
    "autohide_duration",
    "set_autohide_duration",
    "add_spacer",
    "remove_spacers",
    "auto_rearrange_spaces",
    "set_auto_rearrange_spaces",
    "separate_spaces_per_display",
    "set_separate_spaces_per_display",
    "hot_corner_modifiers",
    "dim_hidden_apps",
    "set_dim_hidden_apps",
    "only_open_apps",
    "set_only_open_apps",
    "launch_animation",
    "set_launch_animation",
    "group_windows_by_app",
    "set_group_windows_by_app",
    "switch_to_space_with_app",
    "set_switch_to_space_with_app",
    "DockFolder",
    "folders",
    "add_folder",
    "remove_folder",
]

_DOMAIN = "com.apple.dock"
_POSITIONS = ("left", "bottom", "right")
_FILE_URL = 15  # _CFURLStringType of a file:// URL


@dataclass(frozen=True)
class DockApp:
    """An app kept in the Dock."""

    name: str
    path: Optional[Path]
    bundle_id: Optional[str]


_SETTLE = 1.5  # seconds a new Dock takes to read its settings, and write them back


def _pid() -> Optional[int]:
    for app in _apps.running(include_background=True):
        if app.bundle_id == "com.apple.dock":
            return app.pid
    return None


def restart() -> None:
    """
    Restart the Dock, so it reads its settings again (the other functions do it for you).

    Returns once the new Dock has started, so the next change reaches it.
    """
    if restart_later("Dock", restart):
        return
    require_macos()
    old = _pid()
    # Killed, not asked to quit: a quitting Dock saves the settings it had over the change.
    # launchd starts a new one right away.
    _run(["killall", "-KILL", "Dock"], timeout=10)  # killall only signals: never long
    deadline = time.monotonic() + 10
    while True:
        pid = _pid()
        if pid is not None and pid != old:
            break
        if time.monotonic() > deadline:
            raise MacOSError("the Dock didn't start again within 10 seconds")
        time.sleep(0.1)
    time.sleep(_SETTLE)


def autohide() -> bool:
    """Whether the Dock hides until the pointer reaches the edge of the screen."""
    return bool(defaults.read(_DOMAIN, "autohide", default=False))


def set_autohide(on: bool = True) -> None:
    """Hide the Dock until the pointer reaches the edge of the screen, or keep it shown."""
    defaults.write(_DOMAIN, "autohide", bool(on))
    restart()


def size() -> int:
    """The size of the Dock's icons, in points (16 to 128)."""
    return int(round(float(defaults.read(_DOMAIN, "tilesize", default=64))))


def set_size(points: int) -> None:
    """Set the size of the Dock's icons, from 16 to 128 points, like the Size slider in System Settings."""
    if not 16 <= points <= 128:
        raise ValueError("size must be from 16 to 128 points, not {}".format(points))
    defaults.write(_DOMAIN, "tilesize", float(points))
    restart()


def position() -> str:
    """Where the Dock is: ``'left'``, ``'bottom'`` or ``'right'``."""
    found = defaults.read(_DOMAIN, "orientation", default="bottom")
    return found if found in _POSITIONS else "bottom"


def set_position(where: str) -> None:
    """Move the Dock to the ``'left'``, ``'bottom'`` or ``'right'`` of the screen."""
    if where not in _POSITIONS:
        raise ValueError("position must be 'left', 'bottom' or 'right', not {!r}".format(where))
    defaults.write(_DOMAIN, "orientation", where)
    restart()


def _tiles() -> List[Dict[str, Any]]:
    return list(defaults.read(_DOMAIN, "persistent-apps", default=[]))


def _tile_path(tile: Dict[str, Any]) -> Optional[Path]:
    url = tile.get("tile-data", {}).get("file-data", {}).get("_CFURLString", "")
    if not url.startswith("file://"):
        return None
    # Resolved, like the app paths it's compared with: /Applications/Safari.app is a link.
    return Path(os.path.realpath(unquote(urlparse(url).path).rstrip("/")))


def _is_app(tile: Dict[str, Any]) -> bool:
    if tile.get("tile-type") not in ("file-tile", None):
        return False
    return _tile_path(tile) is not None or bool(tile.get("tile-data", {}).get("file-label"))


def apps() -> List[DockApp]:
    """
    The apps kept in the Dock, left to right (or top to bottom).

    Finder, which always comes first, and the running apps that aren't kept
    aren't listed; nor are spacers.
    """
    found = []
    for tile in _tiles():
        if not _is_app(tile):
            continue  # spacers and the like
        data = tile.get("tile-data", {})
        path = _tile_path(tile)
        name = data.get("file-label") or (path.stem if path else "")
        found.append(DockApp(name=name, path=path, bundle_id=data.get("bundle-identifier")))
    return found


def _matches(tile: Dict[str, Any], app: str) -> bool:
    data = tile.get("tile-data", {})
    path = _tile_path(tile)
    wanted = app.casefold()
    return wanted in (
        str(data.get("file-label", "")).casefold(),
        str(data.get("bundle-identifier", "")).casefold(),
        str(path).casefold() if path else "",
    )


def add_app(app: str, *, index: Optional[int] = None) -> DockApp:
    """
    Keep ``app`` in the Dock, at the end or at ``index`` (in :func:`apps`, so 0 is right after Finder), and return it.

    ``app`` is a name (``"Safari"``), a bundle ID or the path of a ``.app``,
    found as :func:`macos.apps.open` finds apps. An app already kept isn't
    added twice.
    """
    path = Path(_apps._locate(app))
    if not path.exists():
        raise AppNotFoundError("{!r} is not an installed app".format(app))
    tiles = _tiles()
    existing = [tile for tile in tiles if _tile_path(tile) == path]
    if existing:
        return next(entry for entry in apps() if entry.path == path)
    bundle_id = _apps._bundle_id(str(path))
    name = path.stem
    tile = {
        "tile-data": {
            "file-data": {"_CFURLString": "file://{}/".format(quote(str(path))), "_CFURLStringType": _FILE_URL},
            "file-label": name,
            **({"bundle-identifier": bundle_id} if bundle_id else {}),
        },
        "tile-type": "file-tile",
    }
    _insert(tiles, tile, index)
    defaults.write(_DOMAIN, "persistent-apps", tiles)
    restart()
    return DockApp(name=name, path=path, bundle_id=bundle_id)


def _insert(tiles: List[Dict[str, Any]], tile: Dict[str, Any], index: Optional[int]) -> None:
    # index counts the apps apps() lists: find its place among all the tiles, spacers included.
    app_positions = [position for position, entry in enumerate(tiles) if _is_app(entry)]
    if index is None or index >= len(app_positions):
        tiles.append(tile)
    else:
        tiles.insert(app_positions[max(index, 0)], tile)


def remove_app(app: str) -> bool:
    """Take ``app`` (a name, bundle ID or path) out of the Dock; return whether it was there. It stays installed."""
    if not app.strip():
        raise ValueError("remove_app() needs an app's name, bundle ID or path")
    target = os.path.realpath(os.path.expanduser(app)) if app.endswith(".app") else app
    tiles = _tiles()
    # Apps only: a spacer has no label to tell it apart, nor is it an app.
    kept = [tile for tile in tiles if not (_is_app(tile) and _matches(tile, target))]
    if len(kept) == len(tiles):
        return False
    defaults.write(_DOMAIN, "persistent-apps", kept)
    restart()
    return True


# --- More settings ----------------------------------------------------------

_CORNERS = {"top_left": "tl", "top_right": "tr", "bottom_left": "bl", "bottom_right": "br"}
_ACTIONS = {
    None: 1,
    "mission_control": 2,
    "app_windows": 3,
    "desktop": 4,
    "start_screensaver": 5,
    "disable_screensaver": 6,
    "display_sleep": 10,
    "launchpad": 11,
    "notification_center": 12,
    "lock_screen": 13,
    "quick_note": 14,
}
HOT_CORNER_ACTIONS = tuple(action for action in _ACTIONS if action)
"""What a hot corner can do, for :func:`set_hot_corner`."""
# The keys a hot corner can wait for, as the modifier flags the Dock keeps.
_CORNER_MODIFIERS = {"shift": 131072, "ctrl": 262144, "option": 524288, "cmd": 1048576}
_CORNER_MODIFIER_ALIASES = {"command": "cmd", "control": "ctrl", "opt": "option", "alt": "option"}
_EFFECTS = ("genie", "scale")


def hot_corners() -> Dict[str, Optional[str]]:
    """
    What each hot corner does: ``{"top_left": "mission_control", "bottom_right": "desktop", ...}``.

    ``None`` for a corner that does nothing.
    """
    names = {number: action for action, number in _ACTIONS.items()}
    return {
        corner: names.get(int(defaults.read(_DOMAIN, "wvous-{}-corner".format(code), default=1)))
        for corner, code in _CORNERS.items()
    }


def hot_corner_modifiers() -> Dict[str, Optional[str]]:
    """The keys each hot corner waits for, such as ``{"top_left": "cmd", "top_right": None, ...}``."""
    found: Dict[str, Optional[str]] = {}
    for corner, code in _CORNERS.items():
        flags = int(defaults.read(_DOMAIN, "wvous-{}-modifier".format(code), default=0))
        names = [name for name in ("cmd", "shift", "option", "ctrl") if flags & _CORNER_MODIFIERS[name]]
        found[corner] = "+".join(names) or None
    return found


def _corner_flags(modifier: Optional[str]) -> int:
    if not modifier:
        return 0
    flags = 0
    for part in modifier.lower().split("+"):
        name = _CORNER_MODIFIER_ALIASES.get(part.strip(), part.strip())
        if name not in _CORNER_MODIFIERS:
            raise ValueError("modifier must be made of cmd, shift, option and ctrl, not {!r}".format(modifier))
        flags |= _CORNER_MODIFIERS[name]
    return flags


def set_hot_corner(corner: str, action: Optional[str], *, modifier: Optional[str] = None) -> None:
    """
    Make moving the pointer into ``corner`` do ``action``, like System Settings › Desktop & Dock › Hot Corners.

    ::

        macos.dock.set_hot_corner("bottom_right", "lock_screen")
        macos.dock.set_hot_corner("top_left", "mission_control", modifier="cmd")   # only while holding ⌘
        macos.dock.set_hot_corner("top_left", None)                                # nothing

    ``corner`` is ``"top_left"``, ``"top_right"``, ``"bottom_left"`` or
    ``"bottom_right"``; ``action`` one of :data:`HOT_CORNER_ACTIONS`.
    ``modifier`` makes the corner wait for keys held down, so it doesn't
    fire by accident: ``"cmd"``, ``"option"``, ``"cmd+shift"``...
    """
    if corner not in _CORNERS:
        raise ValueError("corner must be one of {}, not {!r}".format(", ".join(_CORNERS), corner))
    if action not in _ACTIONS:
        raise ValueError("action must be one of {} or None, not {!r}".format(", ".join(HOT_CORNER_ACTIONS), action))
    flags = _corner_flags(modifier)
    code = _CORNERS[corner]
    defaults.write(_DOMAIN, "wvous-{}-corner".format(code), _ACTIONS[action])
    defaults.write(_DOMAIN, "wvous-{}-modifier".format(code), flags)
    restart()


def autohide_delay() -> float:
    """Seconds a hidden Dock waits before showing, when the pointer reaches the edge."""
    return float(defaults.read(_DOMAIN, "autohide-delay", default=0.5))


def set_autohide_delay(seconds: float) -> None:
    """Show a hidden Dock after ``seconds`` at the edge: ``0`` shows it at once, a classic tweak."""
    if seconds < 0:
        raise ValueError("seconds must not be negative, not {}".format(seconds))
    defaults.write(_DOMAIN, "autohide-delay", float(seconds))
    restart()


def magnification() -> Optional[int]:
    """The size icons grow to under the pointer, in points; ``None`` when they don't."""
    if not defaults.read(_DOMAIN, "magnification", default=False):
        return None
    return int(round(float(defaults.read(_DOMAIN, "largesize", default=128))))


def set_magnification(size: Optional[int]) -> None:
    """Make icons grow to ``size`` points (16 to 128) under the pointer, or not (``None``)."""
    if size is None:
        defaults.write(_DOMAIN, "magnification", False)
    else:
        if not 16 <= size <= 128:
            raise ValueError("size must be from 16 to 128 points, not {}".format(size))
        defaults.write(_DOMAIN, "magnification", True)
        defaults.write(_DOMAIN, "largesize", float(size))
    restart()


def show_recents() -> bool:
    """Whether the Dock shows recent apps that aren't kept in it, in their own section."""
    return bool(defaults.read(_DOMAIN, "show-recents", default=True))


def set_show_recents(on: bool = True) -> None:
    """Show recent apps in their own section of the Dock, or not."""
    defaults.write(_DOMAIN, "show-recents", bool(on))
    restart()


def minimize_effect() -> str:
    """How windows minimize into the Dock: ``'genie'`` or ``'scale'``."""
    found = defaults.read(_DOMAIN, "mineffect", default="genie")
    return found if found in _EFFECTS else "genie"


def set_minimize_effect(effect: str) -> None:
    """Minimize windows with the ``'genie'`` effect or the quicker ``'scale'``."""
    if effect not in _EFFECTS:
        raise ValueError("effect must be 'genie' or 'scale', not {!r}".format(effect))
    defaults.write(_DOMAIN, "mineffect", effect)
    restart()


def show_indicators() -> bool:
    """Whether the Dock shows a dot under the apps that are open."""
    return bool(defaults.read(_DOMAIN, "show-process-indicators", default=True))


def set_show_indicators(on: bool = True) -> None:
    """Show a dot under open apps, or not."""
    defaults.write(_DOMAIN, "show-process-indicators", bool(on))
    restart()


def minimize_to_app() -> bool:
    """Whether minimized windows go into their app's icon, instead of their own place in the Dock."""
    return bool(defaults.read(_DOMAIN, "minimize-to-application", default=False))


def set_minimize_to_app(on: bool = True) -> None:
    """Minimize windows into their app's icon, or each into its own place at the end of the Dock."""
    defaults.write(_DOMAIN, "minimize-to-application", bool(on))
    restart()


def autohide_duration() -> Optional[float]:
    """Seconds a hidden Dock takes to slide in and out; ``None`` for macOS's own."""
    found = defaults.read(_DOMAIN, "autohide-time-modifier")
    return None if found is None else float(found)


def set_autohide_duration(seconds: Optional[float]) -> None:
    """
    Make a hidden Dock slide in and out in ``seconds``: ``0`` has no animation. ``None`` goes back to macOS's own.

    It adds to the wait of :func:`set_autohide_delay`.
    """
    if seconds is None:
        defaults.delete(_DOMAIN, "autohide-time-modifier")
    else:
        if seconds < 0:
            raise ValueError("seconds must not be negative, not {}".format(seconds))
        defaults.write(_DOMAIN, "autohide-time-modifier", float(seconds))
    restart()


_SPACERS = ("spacer-tile", "small-spacer-tile")


def add_spacer(*, index: Optional[int] = None, small: bool = False) -> None:
    """
    Add a blank space between the Dock's apps, at the end or before the app at ``index`` in :func:`apps`.

    ``small=True`` adds a narrower one. They group the apps, and
    :func:`remove_spacers` takes them all out.
    """
    tiles = _tiles()
    _insert(tiles, {"tile-data": {}, "tile-type": _SPACERS[1] if small else _SPACERS[0]}, index)
    defaults.write(_DOMAIN, "persistent-apps", tiles)
    restart()


def remove_spacers() -> int:
    """Take every blank space out of the Dock's apps; return how many there were."""
    tiles = _tiles()
    kept = [tile for tile in tiles if tile.get("tile-type") not in _SPACERS]
    removed = len(tiles) - len(kept)
    if removed:
        defaults.write(_DOMAIN, "persistent-apps", kept)
        restart()
    return removed


def auto_rearrange_spaces() -> bool:
    """Whether Mission Control reorders the spaces (desktops) by the most recently used."""
    return bool(defaults.read(_DOMAIN, "mru-spaces", default=True))


def set_auto_rearrange_spaces(on: bool = True) -> None:
    """Let Mission Control reorder the spaces by use, or keep them where you put them (``False``)."""
    defaults.write(_DOMAIN, "mru-spaces", bool(on))
    restart()


def separate_spaces_per_display() -> bool:
    """Whether each display has its own spaces (and menu bar), as by default."""
    return not defaults.read("com.apple.spaces", "spans-displays", default=False)


def set_separate_spaces_per_display(on: bool = True) -> None:
    """
    Give each display its own spaces, or share them across the displays (``False``).

    Takes effect at the next login.
    """
    defaults.write("com.apple.spaces", "spans-displays", not on)


def dim_hidden_apps() -> bool:
    """Whether the icons of hidden apps (⌘H) are translucent, to tell them apart."""
    return bool(defaults.read(_DOMAIN, "showhidden", default=False))


def set_dim_hidden_apps(on: bool = True) -> None:
    """Make the icons of hidden apps translucent, or not."""
    defaults.write(_DOMAIN, "showhidden", bool(on))
    restart()


def only_open_apps() -> bool:
    """Whether the Dock shows only the apps that are open, like a taskbar."""
    return bool(defaults.read(_DOMAIN, "static-only", default=False))


def set_only_open_apps(on: bool = True) -> None:
    """Show only the open apps in the Dock, or the apps kept in it too (``False``). The kept apps aren't lost."""
    defaults.write(_DOMAIN, "static-only", bool(on))
    restart()


def launch_animation() -> bool:
    """Whether an app's icon bounces while it opens."""
    return bool(defaults.read(_DOMAIN, "launchanim", default=True))


def set_launch_animation(on: bool = True) -> None:
    """Bounce an app's icon while it opens, or not."""
    defaults.write(_DOMAIN, "launchanim", bool(on))
    restart()


def group_windows_by_app() -> bool:
    """Whether Mission Control groups the windows by app."""
    return bool(defaults.read(_DOMAIN, "expose-group-apps", default=False))


def set_group_windows_by_app(on: bool = True) -> None:
    """Group the windows by app in Mission Control, or spread them out."""
    defaults.write(_DOMAIN, "expose-group-apps", bool(on))
    restart()


def switch_to_space_with_app() -> bool:
    """Whether switching to an app moves to a space (desktop) where it has windows open."""
    return bool(defaults.read(defaults.GLOBAL, "AppleSpacesSwitchOnActivate", default=True))


def set_switch_to_space_with_app(on: bool = True) -> None:
    """
    Move to a space where the app has windows when switching to it, or stay on this space (``False``).

    ``False`` stops the jumps between spaces when ⌘Tab reaches an app that
    has windows elsewhere.
    """
    defaults.write(defaults.GLOBAL, "AppleSpacesSwitchOnActivate", bool(on))
    restart()


# --- Folders ------------------------------------------------------------------

_VIEWS = ("automatic", "fan", "grid", "list")  # showas
_SORTS = {"name": 1, "date_added": 2, "date_modified": 3, "date_created": 4, "kind": 5}  # arrangement
_DISPLAYS = ("stack", "folder")  # displayas


@dataclass(frozen=True)
class DockFolder:
    """A folder kept in the Dock, next to the Trash."""

    name: str
    path: Optional[Path]
    view: str
    """How it opens: ``'automatic'``, ``'fan'``, ``'grid'`` or ``'list'``."""
    sort: str
    """``'name'``, ``'date_added'``, ``'date_modified'``, ``'date_created'`` or ``'kind'``."""
    display: str
    """Its icon: ``'stack'`` (its items piled up) or ``'folder'``."""


def _others() -> List[Dict[str, Any]]:
    return list(defaults.read(_DOMAIN, "persistent-others", default=[]))


def _folder(tile: Dict[str, Any]) -> DockFolder:
    data = tile.get("tile-data", {})
    path = _tile_path(tile)
    sorts = {number: name for name, number in _SORTS.items()}
    view, display = int(data.get("showas", 0)), int(data.get("displayas", 0))
    return DockFolder(
        name=data.get("file-label") or (path.name if path else ""),
        path=path,
        view=_VIEWS[view] if 0 <= view < len(_VIEWS) else "automatic",
        sort=sorts.get(int(data.get("arrangement", 1)), "name"),
        display=_DISPLAYS[display] if 0 <= display < len(_DISPLAYS) else "stack",
    )


def folders() -> List[DockFolder]:
    """The folders kept in the Dock, such as Downloads, left to right (or top to bottom)."""
    return [_folder(tile) for tile in _others() if tile.get("tile-type") == "directory-tile"]


def add_folder(
    folder: Union[str, "os.PathLike[str]"],
    *,
    view: str = "automatic",
    sort: str = "date_added",
    display: str = "stack",
) -> DockFolder:
    """
    Keep ``folder`` in the Dock, next to the Trash, and return it; one kept already is updated.

    ::

        macos.dock.add_folder("~/Downloads", view="grid", sort="date_added")
        macos.dock.add_folder("~/Projects", display="folder", sort="name")

    ``view`` is how it opens (``"automatic"``, ``"fan"``, ``"grid"`` or
    ``"list"``), ``sort`` the order of its items, and ``display`` its icon:
    a ``"stack"`` of its items or the ``"folder"``.
    """
    if view not in _VIEWS:
        raise ValueError("view must be one of {}, not {!r}".format(", ".join(_VIEWS), view))
    if sort not in _SORTS:
        raise ValueError("sort must be one of {}, not {!r}".format(", ".join(_SORTS), sort))
    if display not in _DISPLAYS:
        raise ValueError("display must be 'stack' or 'folder', not {!r}".format(display))
    path = Path(os.path.realpath(os.path.expanduser(str(folder))))
    if not path.is_dir():
        raise NotADirectoryError(str(path))
    tile = {
        "tile-data": {
            "file-data": {"_CFURLString": "file://{}/".format(quote(str(path))), "_CFURLStringType": _FILE_URL},
            "file-label": path.name,
            "file-type": 2,  # a folder
            "showas": _VIEWS.index(view),
            "arrangement": _SORTS[sort],
            "displayas": _DISPLAYS.index(display),
        },
        "tile-type": "directory-tile",
    }
    tiles = _others()
    for index, existing in enumerate(tiles):
        if _tile_path(existing) == path:
            tiles[index] = tile
            break
    else:
        tiles.append(tile)
    defaults.write(_DOMAIN, "persistent-others", tiles)
    restart()
    return _folder(tile)


def remove_folder(folder: Union[str, "os.PathLike[str]"]) -> bool:
    """Take ``folder`` out of the Dock; return whether it was there. The folder itself stays."""
    path = Path(os.path.realpath(os.path.expanduser(str(folder))))
    tiles = _others()
    kept = [tile for tile in tiles if _tile_path(tile) != path]
    if len(kept) == len(tiles):
        return False
    defaults.write(_DOMAIN, "persistent-others", kept)
    restart()
    return True
