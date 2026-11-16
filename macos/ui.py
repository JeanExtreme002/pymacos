# -*- coding: utf-8 -*-

"""
Read what an app shows (its buttons, text fields, links, menus) and use it, without a screenshot.

::

    for element in macos.ui.elements("Calculator"):
        print(element.role, element.name, element.frame)   # AXButton 7 (812, 440, 40, 40)

    macos.ui.find("TextEdit", name="Bold", role="checkbox")[0].press()
    field = macos.ui.find("Safari", role="text field")[0]
    field.set_value("https://example.com")

    for item in macos.ui.menu_items("TextEdit"):
        print(item.path, item.shortcut)                     # ('File', 'Save…') cmd+s
    macos.ui.click_menu_item("Format > Font > Show Fonts", app="TextEdit")

Reads the Accessibility tree that screen readers such as VoiceOver use, so it
needs the *Accessibility* permission for the app running Python (your terminal
or IDE), the same one :mod:`macos.windows` needs. Positions are in points from
the top-left of the main display, as :func:`macos.mouse.click` takes them.
"""

import builtins
import ctypes
import math
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from . import _cf, _objc, apps
from ._objc import CGPoint, CGSize
from .errors import AppNotFoundError, MacOSError, PermissionDeniedError
from .windows import (
    _API_DISABLED,
    _ATTRIBUTE_UNSUPPORTED,
    _CANNOT_COMPLETE,
    _INVALID_ELEMENT,
    _NO_VALUE,
    _SUCCESS,
    _TIMEOUT,
    _accessibility,
    _AXError,
    _copy,
    has_permission,
    request_permission,
)

__all__ = [
    "Element",
    "MenuItem",
    "elements",
    "find",
    "wait_for",
    "focused",
    "at",
    "menu_items",
    "click_menu_item",
    "has_permission",
    "request_permission",
]

_ACTION_UNSUPPORTED = -25206  # kAXErrorActionUnsupported
_NOT_IMPLEMENTED = -25208  # kAXErrorNotImplemented: the app has no accessibility at all
_POINT, _SIZE, _RECT, _RANGE, _ERROR = 1, 2, 3, 4, 5  # AXValueType

#: How many elements a call reads at most, and for how long: a page of thousands of rows would take minutes.
_MOST_VISITED = 6000
_LONGEST_WALK = 15.0
_DEEPEST = 80

# Read in one round trip per element, the slowest part of a walk being the messages to the app.
_ATTRIBUTES = (
    "AXRole",
    "AXSubrole",
    "AXRoleDescription",
    "AXTitle",
    "AXDescription",
    "AXValue",
    "AXHelp",
    "AXPlaceholderValue",
    "AXIdentifier",
    "AXPosition",
    "AXSize",
    "AXEnabled",
    "AXFocused",
    "AXSelected",
    "AXTitleUIElement",
    "AXChildren",
)
_MENU_ATTRIBUTES = (
    "AXRole",
    "AXTitle",
    "AXEnabled",
    "AXSelected",
    "AXMenuItemMarkChar",
    "AXMenuItemCmdChar",
    "AXMenuItemCmdModifiers",
    "AXMenuItemCmdVirtualKey",
    "AXChildren",
)

#: Roles that are there to be used: clicked, typed into, chosen from.
_CONTROLS = frozenset(
    {
        "AXButton",
        "AXCheckBox",
        "AXRadioButton",
        "AXTextField",
        "AXTextArea",
        "AXSecureTextField",
        "AXSearchField",
        "AXComboBox",
        "AXPopUpButton",
        "AXMenuButton",
        "AXSlider",
        "AXIncrementor",
        "AXStepper",
        "AXLink",
        "AXMenuItem",
        "AXMenuBarItem",
        "AXDisclosureTriangle",
        "AXColorWell",
        "AXDateField",
        "AXTimeField",
        "AXDockItem",
        "AXSegment",
        "AXSwitch",
        "AXToggle",
    }
)
#: Subroles that make any role a control: a search field built as static text is still one.
_CONTROL_SUBROLES = frozenset(
    {"AXSearchField", "AXSecureTextField", "AXTabButton", "AXToggle", "AXSwitch", "AXCloseButton",
     "AXMinimizeButton", "AXZoomButton", "AXFullScreenButton", "AXSortButton", "AXTextLink"}
)
#: Roles that hold others, and are never a control themselves, whatever action they advertise.
_CONTAINERS = frozenset(
    {
        "AXApplication",
        "AXWindow",
        "AXSheet",
        "AXDrawer",
        "AXScrollArea",
        "AXSplitGroup",
        "AXSplitter",
        "AXLayoutArea",
        "AXWebArea",
        "AXToolbar",
        "AXTabGroup",
        "AXMenuBar",
        "AXMenu",
        "AXBrowser",
        "AXScrollBar",
        "AXValueIndicator",
        "AXUnknown",
    }
)
#: Rows and cells are chosen by a click: a control when they're selectable, which they say with AXSelected.
_SELECTABLE = frozenset({"AXRow", "AXOutlineRow", "AXTableRow"})
#: What carries text to read, without being a control.
_TEXTS = frozenset({"AXStaticText", "AXHeading", "AXImage", "AXValueIndicator", "AXProgressIndicator",
                    "AXLevelIndicator", "AXBusyIndicator"})
#: What cuts its content to its own frame: what's outside isn't seen.
_CLIPPING = frozenset({"AXScrollArea", "AXWebArea", "AXTable", "AXOutline", "AXList", "AXBrowser", "AXGrid",
                       "AXCollection"})
#: Long lists, whose rows macOS can give a page at a time: the visible ones only.
_LONG = frozenset({"AXTable", "AXOutline", "AXList", "AXBrowser", "AXGrid", "AXCollection"})
#: A role named as a person would, for :func:`find`: "text field", "button"...
_SPOKEN_PREFIX = "AX"


@lru_cache(maxsize=None)
def _ax() -> ctypes.CDLL:
    ax = _accessibility()
    pointer = ctypes.c_void_p
    signatures = {
        "AXUIElementCreateSystemWide": ((), pointer),
        "AXUIElementCopyElementAtPosition": ((pointer, ctypes.c_float, ctypes.c_float, ctypes.POINTER(pointer)),
                                             ctypes.c_int32),
        "AXUIElementCopyActionNames": ((pointer, ctypes.POINTER(pointer)), ctypes.c_int32),
        "AXUIElementCopyMultipleAttributeValues": ((pointer, pointer, ctypes.c_uint32, ctypes.POINTER(pointer)),
                                                   ctypes.c_int32),
        "AXUIElementIsAttributeSettable": ((pointer, pointer, ctypes.POINTER(ctypes.c_bool)), ctypes.c_int32),
        "AXUIElementGetPid": ((pointer, ctypes.POINTER(ctypes.c_int)), ctypes.c_int32),
        "AXUIElementGetTypeID": ((), ctypes.c_ulong),
        "AXValueGetTypeID": ((), ctypes.c_ulong),
        "AXValueGetType": ((pointer,), ctypes.c_int32),
    }
    for name, (argtypes, restype) in signatures.items():
        function = getattr(ax, name)
        function.argtypes = argtypes
        function.restype = restype
    return ax


@lru_cache(maxsize=None)
def _names(attributes: Tuple[str, ...]) -> int:
    """A CFArray of ``attributes``' names, made once and kept: every element is asked for the same ones."""
    return _cf.from_python(builtins.list(attributes))


def _check(status: int, what: str) -> None:
    if status == _SUCCESS:
        return
    if status == _API_DISABLED:
        raise PermissionDeniedError(
            "Accessibility permission is missing: allow the app running Python (your terminal or IDE) in "
            "System Settings › Privacy & Security › Accessibility, then restart it"
        )
    if status == _INVALID_ELEMENT:
        raise _AXError("could not {}: the element is gone (its window closed, or changed)".format(what), status)
    if status == _CANNOT_COMPLETE:
        raise _AXError("could not {}: its app didn't answer (it may be busy, or have quit)".format(what), status)
    if status == _ACTION_UNSUPPORTED:
        raise _AXError("could not {}: the element doesn't do that".format(what), status)
    if status == _ATTRIBUTE_UNSUPPORTED:
        raise _AXError("could not {}: the element has no such attribute".format(what), status)
    raise _AXError("could not {} (AXError {})".format(what, status), status)


def _require_permission(what: str) -> None:
    if not has_permission():
        _check(_API_DISABLED, what)


# --- Values -------------------------------------------------------------------------


def _python(ref: Optional[int]) -> Any:
    """What an attribute's value is in Python: text, a number, a flag, a point or a size; ``None`` for the rest."""
    if not ref:
        return None
    cf, ax = _cf.lib(), _ax()
    kind = cf.CFGetTypeID(ref)
    if kind == cf.CFStringGetTypeID():
        return _cf.to_str(ref)
    if kind == cf.CFBooleanGetTypeID():
        return _cf.to_bool(ref)
    if kind == cf.CFNumberGetTypeID():
        try:
            return _cf.to_python(ref)
        except MacOSError:
            return _cf.to_int(ref)
    if kind == ax.AXValueGetTypeID():
        value_type = ax.AXValueGetType(ref)
        holder: Any
        if value_type == _POINT:
            holder = CGPoint()
        elif value_type == _SIZE:
            holder = CGSize()
        elif value_type == _RECT:
            holder = _objc.CGRect()
        elif value_type == _RANGE:
            holder = _cf.CFRange()
        else:
            return None  # an error in place of a value (kAXValueAXErrorType), or a type with no meaning here
        if not ax.AXValueGetValue(ref, value_type, ctypes.byref(holder)):
            return None
        if value_type == _POINT:
            return (holder.x, holder.y)
        if value_type == _SIZE:
            return (holder.width, holder.height)
        if value_type == _RECT:
            return (holder.origin.x, holder.origin.y, holder.size.width, holder.size.height)
        return (holder.location, holder.length)
    return None


def _is_element(ref: Optional[int]) -> bool:
    return _cf.is_type(ref, _ax().AXUIElementGetTypeID())


def _read_many(element: int, attributes: Tuple[str, ...]) -> Tuple[int, Dict[str, Optional[int]]]:
    """
    The status and the values of ``attributes``, in one message to the app.

    The values are borrowed from the array, returned owned as ``"_array"``: release it, and only it, when done.
    A missing attribute is ``None``.
    """
    array = ctypes.c_void_p()
    status = _ax().AXUIElementCopyMultipleAttributeValues(element, _names(attributes), 0, ctypes.byref(array))
    if status != _SUCCESS or not array.value:
        return status, {}
    found: Dict[str, Optional[int]] = {"_array": array.value}
    error_type = _ax().AXValueGetTypeID()
    for name, value in zip(attributes, _cf.items(array.value)):
        missing = not value or (_cf.lib().CFGetTypeID(value) == error_type and _ax().AXValueGetType(value) == _ERROR)
        found[name] = None if missing else value
    return status, found


def _actions(element: int) -> List[str]:
    names = ctypes.c_void_p()
    if _ax().AXUIElementCopyActionNames(element, ctypes.byref(names)) != _SUCCESS or not names.value:
        return []
    with _cf.owned(names.value):
        return [name for name in (_cf.to_str(item) for item in _cf.items(names.value)) if name]


def _pid(element: int) -> int:
    pid = ctypes.c_int()
    _ax().AXUIElementGetPid(element, ctypes.byref(pid))
    return pid.value


def _to_cf(value: Union[str, float, bool]) -> int:
    """An owned CF value for ``value``: a string, a number or a flag."""
    if isinstance(value, bool):
        return _cf.retain(_cf.constant(_cf.lib(), "kCFBooleanTrue" if value else "kCFBooleanFalse"))
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise ValueError("value must be finite, not {}".format(value))
        return _cf.number(value)
    if isinstance(value, str):
        return _cf.string(value)
    raise ValueError("value must be text, a number or True/False, not {!r}".format(value))


# --- Elements -----------------------------------------------------------------------


def _short_role(role: str) -> str:
    """``"AXPopUpButton"`` as ``"pop up button"``, the way :func:`find` takes a role too."""
    name = role[len(_SPOKEN_PREFIX):] if role.startswith(_SPOKEN_PREFIX) else role
    words = []
    for index, letter in enumerate(name):
        if letter.isupper() and index and not name[index - 1].isupper():
            words.append(" ")
        words.append(letter.lower())
    return "".join(words)


# Marks that set the direction of text, which apps put around numbers and names: invisible, and in the way of a search.
_DIRECTION_MARKS = dict.fromkeys(map(ord, "\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"))


def _clean(value: Any) -> Any:
    return value.translate(_DIRECTION_MARKS) if isinstance(value, str) else value


def _text(value: Any) -> Optional[str]:
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, str):
        return None
    return _clean(value).strip() or None


class Element:
    """
    One thing an app shows: a button, a text field, a link, a menu item, a piece of text...

    Its fields (:attr:`role`, :attr:`name`, :attr:`value`, :attr:`frame`...)
    are as they were when it was found: find it again to see a change. Its
    methods act on it now, and raise :class:`~macos.errors.MacOSError` when
    it's gone (its window closed, or the app redrew it). Get elements with
    :func:`elements`, :func:`find`, :func:`focused` or :func:`at`.
    """

    def __init__(self, element: int, fields: Dict[str, Any], *, app: str, pid: int) -> None:
        # ``element`` is an owned reference, released with the object.
        self._element = element
        self.app = app
        """The name of the app it belongs to, such as ``'Safari'``."""
        self.pid = pid
        """The app's process ID."""
        self.role: str = fields.get("AXRole") or "AXUnknown"
        """What it is, as macOS names it: ``'AXButton'``, ``'AXTextField'``, ``'AXLink'``..."""
        self.subrole: Optional[str] = fields.get("AXSubrole")
        """What it's for, when its role isn't enough: ``'AXSearchField'``, ``'AXCloseButton'``...; or ``None``."""
        self.role_description: str = fields.get("AXRoleDescription") or _short_role(self.role)
        """Its role in the user's language, as VoiceOver says it: ``'button'``, ``'text field'``..."""
        self.title: Optional[str] = _text(fields.get("AXTitle"))
        """The text it shows as its label (a button's), or ``None``."""
        self.description: Optional[str] = _text(fields.get("AXDescription"))
        """What it is, for those who can't see it (an icon button's), or ``None``."""
        self.help: Optional[str] = _text(fields.get("AXHelp"))
        """Its tooltip, or ``None``."""
        self.placeholder: Optional[str] = _text(fields.get("AXPlaceholderValue"))
        """The hint an empty text field shows, or ``None``."""
        self.identifier: Optional[str] = _text(fields.get("AXIdentifier"))
        """The name its developer gave it, steady across languages and launches, or ``None``."""
        value = fields.get("AXValue")
        self.value: Union[str, float, bool, None] = None if isinstance(value, tuple) else _clean(value)
        """
        What it holds: a text field's text, a slider's position, a checkbox's state (``0``, ``1``, or ``2``
        for mixed); ``None`` when it holds nothing.
        """
        self.enabled: bool = fields.get("AXEnabled") is not False
        """Whether it can be used now: a dimmed button can't."""
        self.focused: bool = bool(fields.get("AXFocused"))
        """Whether keystrokes go to it."""
        self.selected: bool = bool(fields.get("AXSelected"))
        """Whether it's chosen: a row, a tab, a cell."""
        self.actions: List[str] = fields.get("_actions") or []
        """What it can be asked to do, such as ``'AXPress'`` or ``'AXShowMenu'``, for :meth:`perform`."""
        position, size = fields.get("AXPosition"), fields.get("AXSize")
        self.frame: Optional[Tuple[int, int, int, int]] = (
            (round(position[0]), round(position[1]), round(size[0]), round(size[1])) if position and size else None
        )
        """``(x, y, width, height)`` in points from the top-left of the main display, or ``None``."""
        self._label: Optional[str] = _text(fields.get("_label"))
        self._web = bool(fields.get("_web"))

    def __del__(self) -> None:
        element, self._element = getattr(self, "_element", 0), 0
        if element:
            _cf.release(element)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Element):
            return NotImplemented
        return bool(_cf.lib().CFEqual(self._element, other._element))

    __hash__ = None  # type: ignore[assignment]

    def __repr__(self) -> str:
        return "Element(role={!r}, name={!r}, frame={!r})".format(self.role, self.name, self.frame)

    @property
    def name(self) -> Optional[str]:
        """
        What a person would call it: its title, the label next to it, its description, or its text.

        ``None`` when it has none of these, as an unlabelled icon button.
        """
        for text in (self.title, self._label, self.description):
            if text:
                return text
        if self.role in _TEXTS or self.role in ("AXMenuItem", "AXMenuBarItem"):
            return _text(self.value) if isinstance(self.value, str) else None
        if self.help or self.placeholder:
            return self.help or self.placeholder
        # A window's close button has no label: what it is says it ("close button").
        return self.role_description if self.role in _CONTROLS and self.subrole and self.subrole != "AXUnknown" else None

    @property
    def center(self) -> Optional[Tuple[int, int]]:
        """``(x, y)`` of its middle, where a click lands; ``None`` when it has no :attr:`frame`."""
        if self.frame is None:
            return None
        x, y, width, height = self.frame
        return (x + width // 2, y + height // 2)

    @property
    def checked(self) -> Optional[bool]:
        """
        For a checkbox, a radio button, a switch or a disclosure triangle, whether it's on; ``None`` otherwise.

        A checkbox in a mixed state (some of what it stands for on, as a
        "select all") is ``None`` too: see its :attr:`value`, ``2``.
        """
        if self.role not in ("AXCheckBox", "AXRadioButton", "AXDisclosureTriangle", "AXSwitch", "AXToggle"):
            return None
        if isinstance(self.value, bool):
            return self.value
        if isinstance(self.value, (int, float)) and self.value in (0, 1):
            return bool(self.value)
        return None

    @property
    def is_control(self) -> bool:
        """Whether it's there to be used (clicked, typed into, chosen from) rather than read."""
        return _is_control(self.role, self.subrole, self.actions, self.selected, web=self._web)

    def _act(self, action: str, what: str) -> None:
        with _cf.owned(_cf.string(action)) as name:
            _check(_ax().AXUIElementPerformAction(self._element, name), what)

    def perform(self, action: str) -> None:
        """
        Ask it to do one of its :attr:`actions`: ``"AXPress"``, ``"AXShowMenu"``, ``"AXIncrement"``, ``"AXConfirm"``...

        Raises :class:`~macos.errors.MacOSError` when it doesn't do that.
        """
        if not isinstance(action, str) or not action:
            raise ValueError("action must be the name of one, such as 'AXPress', not {!r}".format(action))
        self._act(action, "perform {} on the element".format(action))

    def press(self) -> None:
        """
        Use it as a click would: press a button, follow a link, toggle a checkbox, choose a menu item.

        It's done through Accessibility, so the pointer doesn't move and the
        window needn't be in front. An element that can't be pressed that way
        (a row, a web control built from plain boxes) is clicked in its
        middle instead, which needs it to be on screen and uncovered.
        """
        if "AXPress" in self.actions or (not self.actions and self.role in _CONTROLS):
            try:
                self._act("AXPress", "press the element")
                return
            except _AXError as error:
                if error.status != _ACTION_UNSUPPORTED:
                    raise
        self.click()

    def click(self, *, button: str = "left", count: int = 1) -> None:
        """
        Click its middle with the mouse, as :func:`macos.mouse.click` would: ``count=2`` double-clicks.

        Brings its app to the front first, so the click lands on it rather
        than on a window over it.
        """
        from . import mouse

        if self.center is None:
            raise MacOSError("the element has no position on screen to click")
        _bring_to_front(self.pid)
        mouse.click(*self.center, button=button, count=count)

    def set_value(self, value: Union[str, float, bool]) -> None:
        """
        Set what it holds: a text field's text (replacing it), a slider's position, a checkbox's state.

        Raises :class:`~macos.errors.MacOSError` when it can't be set this
        way; type into it instead (:meth:`focus`, then
        :func:`macos.keyboard.type`). Some web forms don't notice a value set
        this way either, and need it typed.
        """
        settable = ctypes.c_bool()
        with _cf.owned(_cf.string("AXValue")) as name:
            status = _ax().AXUIElementIsAttributeSettable(self._element, name, ctypes.byref(settable))
            _check(status, "set the element's value")
            if not settable.value:
                raise MacOSError(
                    "the element's value can't be set (a {}): focus it and type instead".format(self.role_description)
                )
            with _cf.owned(_to_cf(value)) as new:
                _check(_ax().AXUIElementSetAttributeValue(self._element, name, new), "set the element's value")

    def focus(self) -> None:
        """Bring its app to the front and give it the keyboard focus, for what's typed next to go to it."""
        _bring_to_front(self.pid)
        true = _cf.constant(_cf.lib(), "kCFBooleanTrue")
        with _cf.owned(_cf.string("AXFocused")) as name:
            _check(_ax().AXUIElementSetAttributeValue(self._element, name, true), "focus the element")

    def children(self) -> "builtins.list[Element]":
        """What it holds, as it is now, in the order the app gives them: everything, not only controls."""
        status, value = _copy(self._element, "AXChildren")
        if status not in (_SUCCESS, _NO_VALUE, _ATTRIBUTE_UNSUPPORTED):
            _check(status, "read the element's children")
        with _cf.owned(value):
            return [_make(child, self.app, self.pid) for child in _cf.items(value) if _is_element(child)]

    def text(self) -> str:
        """
        All the text it holds, its own and its children's, top to bottom: a web page's, a message's, a dialog's.

        Reads its whole content, what's scrolled out of view included.
        """
        lines: List[str] = []
        _gather_text(self._element, lines, 0, _Budget())
        return "\n".join(lines)


def _make(element: int, app: str, pid: int, *, labels: bool = True) -> Element:
    """An :class:`Element` for a borrowed ``element``, read now (in one message to its app)."""
    _ax().AXUIElementSetMessagingTimeout(element, _TIMEOUT)
    status, raw = _read_many(element, _ATTRIBUTES)
    if status == _API_DISABLED:
        _check(status, "read the element")
    try:
        fields = _fields(raw, labels=labels)
    finally:
        _cf.release(raw.get("_array"))
    fields["_actions"] = _actions(element)
    return Element(_cf.retain(element), fields, app=app, pid=pid)


def _fields(raw: Dict[str, Optional[int]], *, labels: bool) -> Dict[str, Any]:
    fields = {name: _python(value) for name, value in raw.items() if name not in ("_array", "AXChildren", "AXTitleUIElement")}
    label = raw.get("AXTitleUIElement")
    if labels and label and _is_element(label):
        status, text = _copy(label, "AXValue")
        with _cf.owned(text):
            fields["_label"] = _cf.to_str(text) if status == _SUCCESS else None
    return fields


def _is_control(role: str, subrole: Optional[str], actions: Sequence[str], selected: bool, *, web: bool = False) -> bool:
    if role in _CONTROLS or (subrole and subrole in _CONTROL_SUBROLES):
        return True
    if role in _CONTAINERS or role in _TEXTS:
        return False
    if role in _SELECTABLE:
        return True
    # Outside a web page, a plain box (AXGroup) that says it can be pressed is a control. In one, Chrome says
    # it of every paragraph: a page's controls are told by their role (a button, a link), which ARIA sets.
    return "AXPress" in actions and not web


def _bring_to_front(pid: int) -> None:
    element = _accessibility().AXUIElementCreateApplication(pid)
    if not element:
        return
    try:
        _ax().AXUIElementSetMessagingTimeout(element, _TIMEOUT)
        true = _cf.constant(_cf.lib(), "kCFBooleanTrue")
        with _cf.owned(_cf.string("AXFrontmost")) as name:
            _accessibility().AXUIElementSetAttributeValue(element, name, true)
    finally:
        _cf.release(element)


# --- Walking an app -------------------------------------------------------------------


class _Budget:
    """How much of an app a walk may still read, so a huge page can't keep it going for minutes."""

    def __init__(self) -> None:
        self.left = _MOST_VISITED
        self.deadline = time.monotonic() + _LONGEST_WALK
        self.cut = False
        self.menus: List[Tuple[int, int]] = []  # where in what's found the menus open on screen are

    def spend(self) -> bool:
        if self.left <= 0 or time.monotonic() > self.deadline:
            self.cut = True
            return False
        self.left -= 1
        return True


_Rect = Tuple[float, float, float, float]


def _intersection(first: _Rect, second: _Rect) -> Optional[_Rect]:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right = min(first[0] + first[2], second[0] + second[2])
    bottom = min(first[1] + first[3], second[1] + second[3])
    if right <= left or bottom <= top:
        return None
    return (left, top, right - left, bottom - top)


def _inside(point: Tuple[float, float], rect: _Rect) -> bool:
    return rect[0] <= point[0] < rect[0] + rect[2] and rect[1] <= point[1] < rect[1] + rect[3]


def _app_of(app: Union[str, apps.App, None]) -> apps.App:
    if isinstance(app, apps.App):
        return app
    if app is None:
        found = apps.frontmost()
        if found is None:
            raise MacOSError("no app is in front")
        return found
    found = apps.get(app)
    if found is None:
        raise AppNotFoundError("no running app goes by {!r}: open it first".format(app))
    return found


def _application(pid: int) -> int:
    """An owned element for the app, its web content made readable (Chromium and Electron hide it otherwise)."""
    element = _accessibility().AXUIElementCreateApplication(pid)
    if not element:
        raise MacOSError("could not reach the app with pid {}".format(pid))
    _ax().AXUIElementSetMessagingTimeout(element, _TIMEOUT)
    true = _cf.constant(_cf.lib(), "kCFBooleanTrue")
    with _cf.owned(_cf.string("AXManualAccessibility")) as name:
        _accessibility().AXUIElementSetAttributeValue(element, name, true)  # refused by apps that don't need it
    return int(element)


def _owned_list(element: int, attribute: str) -> List[int]:
    """The elements in a list attribute, each retained (owned): release each one."""
    status, value = _copy(element, attribute)
    if status == _API_DISABLED:
        _check(status, "read the app")
    with _cf.owned(value):
        return [_cf.retain(item) for item in _cf.items(value) if _is_element(item)]


def _flag(element: int, attribute: str) -> bool:
    status, value = _copy(element, attribute)
    with _cf.owned(value):
        return status == _SUCCESS and _cf.to_bool(value)


def _role(element: int) -> Optional[str]:
    status, value = _copy(element, "AXRole")
    with _cf.owned(value):
        return _cf.to_str(value) if status == _SUCCESS else None


def _frame_of(element: int) -> Optional[_Rect]:
    status, raw = _read_many(element, ("AXPosition", "AXSize"))
    try:
        position, size = _python(raw.get("AXPosition")), _python(raw.get("AXSize"))
    finally:
        _cf.release(raw.get("_array"))
    if status != _SUCCESS or not position or not size:
        return None
    return (position[0], position[1], size[0], size[1])


def _roots(application: int) -> List[Tuple[int, Optional[_Rect]]]:
    """
    Where to look in the app, front first, each owned and with the frame that clips it.

    An open menu or a modal dialog shuts out the rest, which can't be used meanwhile: only it is walked. A
    sheet (a save panel over a document) does the same to its window. Minimized windows are left out.
    """
    open_menus = _children(application, lambda role: role == "AXMenu")  # a context menu
    menu_bar = _copy(application, "AXMenuBar")[1]
    with _cf.owned(menu_bar):
        if menu_bar:
            for item in _owned_list(menu_bar, "AXChildren"):
                if _flag(item, "AXSelected"):  # a menu of the menu bar is open
                    open_menus.extend(_children(item, lambda role: role == "AXMenu"))
                _cf.release(item)
    if open_menus:
        return [(menu, None) for menu in open_menus]

    shown = []
    for window in _owned_list(application, "AXWindows"):
        if _flag(window, "AXMinimized"):
            _cf.release(window)
        else:
            shown.append(window)
    modal = [window for window in shown if _flag(window, "AXModal")]
    if modal:
        chosen = modal
    else:
        # The window in front, and the panels that float over the app's windows (Fonts, an inspector): the
        # windows behind it are mostly covered, and their controls would pass for its own.
        chosen, standard_seen = [], False
        for window in shown:
            standard = _subrole(window) == "AXStandardWindow"
            if not standard or not standard_seen:
                chosen.append(window)
            standard_seen = standard_seen or standard
    for window in shown:
        if window not in chosen:
            _cf.release(window)

    roots: List[Tuple[int, Optional[_Rect]]] = []
    for window in chosen:
        frame = _frame_of(window)
        sheets = _children(window, lambda role: role == "AXSheet")
        if sheets:  # a save panel over a document: the document can't be used meanwhile
            roots.extend((sheet, frame) for sheet in sheets)
            _cf.release(window)
        else:
            roots.append((window, frame))
    if not roots:  # no window: an app such as the Dock shows itself through its other children
        roots = [(child, None) for child in _children(application, lambda role: role != "AXMenuBar")]
    return roots


def _children(element: int, keep: Callable[[Optional[str]], bool]) -> List[int]:
    """The children of ``element`` whose role ``keep`` accepts, each owned: release each one."""
    kept = []
    for child in _owned_list(element, "AXChildren"):
        if keep(_role(child)):
            kept.append(child)
        else:
            _cf.release(child)
    return kept


def _subrole(element: int) -> Optional[str]:
    status, value = _copy(element, "AXSubrole")
    with _cf.owned(value):
        return _cf.to_str(value) if status == _SUCCESS else None


def _walk(
    element: int,
    clip: Optional[_Rect],
    covers: Sequence[_Rect],
    depth: int,
    budget: _Budget,
    found: List[Tuple[int, Dict[str, Any]]],
    web: bool = False,
) -> None:
    """Add to ``found`` the elements under ``element`` that show, each retained with its fields, in reading order."""
    if depth > _DEEPEST or not budget.spend():
        return
    _ax().AXUIElementSetMessagingTimeout(element, _TIMEOUT)
    status, raw = _read_many(element, _ATTRIBUTES)
    if status != _SUCCESS:
        if status == _API_DISABLED:
            _check(status, "read the app")
        return
    index = menu_start = None
    try:
        fields = _fields(raw, labels=True)
        role = fields.get("AXRole") or ""
        position, size = fields.get("AXPosition"), fields.get("AXSize")
        frame = (position[0], position[1], size[0], size[1]) if position and size else None
        if frame and frame[2] > 0 and frame[3] > 0 and clip is not None:
            if _intersection(frame, clip) is None:
                return  # scrolled out of view, with all it holds
        # Chrome squashes what's scrolled out of a page to a line at its edge, rather than leaving it outside.
        hidden = frame is None or frame[2] <= 1 or frame[3] <= 1
        if frame and not hidden:
            middle = (frame[0] + frame[2] / 2, frame[1] + frame[3] / 2)
            hidden = any(_inside(middle, cover) for cover in covers)  # under a window in front
        if role == "AXMenuItem" and not _text(fields.get("AXTitle")):
            hidden = True  # a separator
        if role == "AXMenu" and not hidden:
            menu_start = len(found)
        if not hidden and role not in _CONTAINERS:
            undecided = role not in _CONTROLS and role not in _TEXTS
            fields["_actions"] = _actions(element) if undecided or role in _CONTROLS else []
            fields["_web"] = web
            index = len(found)
            found.append((_cf.retain(element), fields))
        if role in _CLIPPING and frame and frame[2] > 0 and frame[3] > 0:
            clip = _intersection(frame, clip) if clip is not None else frame
            if clip is None:
                return
        web = web or role == "AXWebArea"
        children = raw.get("AXChildren")
        child_list = _cf.items(children)
        if role in _LONG:
            visible = _copy(element, "AXVisibleRows" if role in ("AXTable", "AXOutline") else "AXVisibleChildren")[1]
            if visible:
                with _cf.owned(visible):
                    # Retained for the walk: the array goes when this block ends.
                    held = [_cf.retain(item) for item in _cf.items(visible)]
                try:
                    for child in held:
                        _visit(child, clip, covers, depth, budget, found, web)
                finally:
                    for child in held:
                        _cf.release(child)
                return
        for child in child_list:
            _visit(child, clip, covers, depth, budget, found, web)
    finally:
        _cf.release(raw.get("_array"))
        if index is not None and _wraps_controls(found, index):
            _cf.release(found.pop(index)[0])
        if menu_start is not None:
            budget.menus.append((menu_start, len(found)))


def _entry_is_control(fields: Dict[str, Any]) -> bool:
    return _is_control(fields.get("AXRole") or "", fields.get("AXSubrole"), fields.get("_actions") or [],
                       bool(fields.get("AXSelected")), web=bool(fields.get("_web")))


def _wraps_controls(found: List[Tuple[int, Dict[str, Any]]], index: int) -> bool:
    """
    Whether ``found[index]`` is only a box around controls, found after it: a web page's clickable ``div``.

    It says it can be pressed, but has no name and isn't a control by its role; what's in it is what to use.
    """
    fields = found[index][1]
    if fields.get("AXRole") in _CONTROLS or not _entry_is_control(fields):
        return False
    if any(_text(fields.get(name)) for name in ("AXTitle", "_label", "AXDescription", "AXHelp")):
        return False
    return any(_entry_is_control(other) for _, other in found[index + 1:])


def _visit(
    child: int,
    clip: Optional[_Rect],
    covers: Sequence[_Rect],
    depth: int,
    budget: _Budget,
    found: List[Tuple[int, Dict[str, Any]]],
    web: bool,
) -> None:
    if _is_element(child):
        _walk(child, clip, covers, depth + 1, budget, found, web)


def _elements_of(application: int) -> Tuple[List[Tuple[int, Dict[str, Any]]], bool]:
    found: List[Tuple[int, Dict[str, Any]]] = []
    budget = _Budget()
    covers: List[_Rect] = []
    roots = _roots(application)
    try:
        for root, clip in roots:
            _walk(root, clip, builtins.list(covers), 0, budget, found)
            if clip is not None:
                covers.append(clip)  # what's behind this window, in the next ones, can't be seen
    finally:
        for root, _ in roots:
            _cf.release(root)
    if budget.menus:  # a pop-up menu is open: nothing else can be used until it closes
        kept = [entry for start, end in budget.menus for entry in found[start:end]]
        mine = {element for element, _ in kept}
        for element, _ in found:
            if element not in mine:
                _cf.release(element)
        found = kept
    return found, budget.cut


def _matches(element: Element, name: Optional[str], role: Optional[str]) -> bool:
    if role is not None:
        wanted = role.casefold().replace("_", " ").strip()
        names = {element.role, element.subrole or "", element.role_description}
        spoken = {_short_role(part).casefold() for part in names if part} | {part.casefold() for part in names if part}
        if wanted not in spoken:
            return False
    if name is not None:
        wanted_name = name.casefold().strip()
        texts = (element.name, element.title, element.description, element.placeholder, element.identifier,
                 element.help, element.value if isinstance(element.value, str) else None)
        if not any(text and wanted_name in text.casefold() for text in texts):
            return False
    return True


def _collect(app: Union[str, apps.App, None], what: str) -> Tuple[apps.App, List[Element], bool]:
    _require_permission(what)
    target = _app_of(app)
    application = _application(target.pid)
    try:
        raw, cut = _elements_of(application)
    finally:
        _cf.release(application)
    name = target.name or ""
    return target, [Element(element, fields, app=name, pid=target.pid) for element, fields in raw], cut


def elements(
    app: Union[str, apps.App, None] = None, *, controls_only: bool = True
) -> "builtins.list[Element]":
    """
    Return what the app shows on screen, top to bottom: its buttons, text fields, links, checkboxes, menus...

    ``app`` is a running app's name, bundle identifier or path, or an
    :class:`~macos.apps.App`; the app in front by default. Only what can be
    seen is listed: what's scrolled out of view, behind another of its
    windows, or in a minimized one is left out. When a menu, a modal dialog
    or a sheet is open, only it is, since nothing else can be used
    meanwhile. ``controls_only=False`` adds what's there to be read: text,
    headings, images with a description.

    Web pages are read too, in Safari, Chrome and Electron apps. A page of
    thousands of elements is cut after a few thousand, or 15 seconds.
    Raises :class:`~macos.errors.AppNotFoundError` for an app that isn't
    running.
    """
    _, found, _ = _collect(app, "read the app")
    return [element for element in found if element.is_control or (not controls_only and _has_text(element))]


def _has_text(element: Element) -> bool:
    return bool(element.name or (isinstance(element.value, str) and element.value.strip()))


def find(
    app: Union[str, apps.App, None] = None,
    *,
    name: Optional[str] = None,
    role: Optional[str] = None,
) -> "builtins.list[Element]":
    """
    Return the elements on screen whose name contains ``name`` (ignoring case), of ``role``, top to bottom.

    ::

        macos.ui.find("Safari", name="Reload")
        macos.ui.find(role="text field")            # in the app in front
        macos.ui.find("Mail", name="Send", role="button")[0].press()

    ``name`` is looked for in the element's :attr:`~Element.name`, title,
    description, placeholder, tooltip, identifier and text. ``role`` is
    macOS's (``"AXButton"``), said plainly (``"button"``, ``"text field"``,
    ``"pop up button"``), its subrole (``"search field"``), or as the user's
    language says it. Text is found too, not only controls. ``app`` works as
    in :func:`elements`.
    """
    if name is None and role is None:
        raise ValueError("give a name, a role, or both: elements() lists everything")
    _, found, _ = _collect(app, "read the app")
    return [element for element in found if (element.is_control or _has_text(element)) and _matches(element, name, role)]


def wait_for(
    app: Union[str, apps.App, None] = None,
    *,
    name: Optional[str] = None,
    role: Optional[str] = None,
    timeout: Optional[float] = 10.0,
    interval: float = 0.5,
) -> Optional[Element]:
    """
    Wait until an element shows up, and return it; ``None`` if ``timeout`` seconds pass first.

    ``name``, ``role`` and ``app`` work as in :func:`find`, which is asked
    again every ``interval`` seconds. ``timeout=None`` waits until it shows
    up. An app that isn't running yet is waited for too. Handy after an
    action that takes a while::

        macos.ui.find("Safari", role="text field")[0].set_value("example.com")
        macos.ui.wait_for("Safari", name="Example Domain")
    """
    if not interval > 0:
        raise ValueError("interval must be positive, not {}".format(interval))
    if timeout is not None and math.isnan(timeout):
        raise ValueError("timeout must be a number of seconds or None, not nan")
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        try:
            found = find(app, name=name, role=role)
        except AppNotFoundError:
            found = []
        if found:
            return found[0]
        if deadline is not None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            time.sleep(min(interval, remaining))
        else:
            time.sleep(interval)


def _system_wide() -> int:
    element = _ax().AXUIElementCreateSystemWide()
    if not element:
        raise MacOSError("could not reach Accessibility")
    return int(element)


def _app_name(pid: int) -> str:
    with _objc.autorelease_pool():
        handle = apps._handle(pid)
        found = apps._app(handle) if handle else None
    return (found.name if found else None) or ""


def focused() -> Optional[Element]:
    """Return the element keystrokes go to (a text field, a list...), in whichever app; ``None`` when there's none."""
    _require_permission("read the focused element")
    system = _system_wide()
    try:
        _ax().AXUIElementSetMessagingTimeout(system, _TIMEOUT)
        status, value = _copy(system, "AXFocusedUIElement")
    finally:
        _cf.release(system)
    if status == _API_DISABLED:
        _check(status, "read the focused element")
    if not value:
        # Asked of every app at once, macOS may not answer (a process it won't relay for): ask the one in front.
        front = apps.frontmost()
        if front is None:
            return None
        application = _application(front.pid)
        try:
            status, value = _copy(application, "AXFocusedUIElement")
        finally:
            _cf.release(application)
        if status == _API_DISABLED:
            _check(status, "read the focused element")
    if not value:
        return None
    with _cf.owned(value):
        pid = _pid(value)
        return _make(value, _app_name(pid), pid)


def at(x: float, y: float) -> Optional[Element]:
    """
    Return the element at ``(x, y)``, in whichever app shows it there: the one a click there would reach.

    In points from the top-left of the main display. ``None`` when nothing
    answers there (the desktop, or an app that doesn't answer).
    """
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ValueError("x and y must be finite, not {}, {}".format(x, y))
    _require_permission("read the element at a position")
    system = _system_wide()
    value = ctypes.c_void_p()
    try:
        _ax().AXUIElementSetMessagingTimeout(system, _TIMEOUT)
        status = _ax().AXUIElementCopyElementAtPosition(system, x, y, ctypes.byref(value))
    finally:
        _cf.release(system)
    if status == _API_DISABLED:
        _check(status, "read the element at a position")
    if status != _SUCCESS or not value.value:
        return None
    with _cf.owned(value.value):
        pid = _pid(value.value)
        return _make(value.value, _app_name(pid), pid)


def _gather_text(element: int, lines: List[str], depth: int, budget: _Budget) -> None:
    if depth > _DEEPEST or not budget.spend():
        return
    status, raw = _read_many(element, ("AXRole", "AXTitle", "AXValue", "AXDescription", "AXChildren"))
    if status != _SUCCESS:
        if status == _API_DISABLED:
            _check(status, "read the element's text")
        return
    try:
        role = _python(raw.get("AXRole")) or ""
        texts = [_python(raw.get(name)) for name in ("AXTitle", "AXValue", "AXDescription")]
        for text in texts:
            if isinstance(text, str) and text.strip() and (not lines or lines[-1] != text.strip()):
                if role in ("AXStaticText", "AXTextArea", "AXTextField", "AXHeading", "AXLink", "AXButton",
                            "AXCell", "AXMenuItem", "AXCheckBox", "AXRadioButton", "AXImage", "AXWindow", "AXSheet"):
                    lines.append(text.strip())
                    break
        for child in _cf.items(raw.get("AXChildren")):
            if _is_element(child):
                _gather_text(child, lines, depth + 1, budget)
    finally:
        _cf.release(raw.get("_array"))


# --- Menus ------------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuItem:
    """An item of an app's menus, from :func:`menu_items`."""

    path: Tuple[str, ...]
    """Where it is, menu by menu: ``('File', 'Export', 'PDF…')``, for :func:`click_menu_item`."""
    enabled: bool
    """Whether it can be chosen now: a dimmed item can't."""
    checked: bool
    """Whether it shows a check mark, as a setting that's on."""
    shortcut: Optional[str]
    """Its keyboard shortcut, as :func:`macos.keyboard.press` takes it (``'cmd+shift+s'``), or ``None``."""


# Keys a shortcut may use that have no character of their own, by their virtual key code.
_VIRTUAL_KEYS = {
    36: "return", 48: "tab", 49: "space", 51: "delete", 53: "escape", 117: "forward_delete", 115: "home",
    119: "end", 116: "page_up", 121: "page_down", 123: "left", 124: "right", 125: "down", 126: "up",
    122: "f1", 120: "f2", 99: "f3", 118: "f4", 96: "f5", 97: "f6", 98: "f7", 100: "f8", 101: "f9",
    109: "f10", 103: "f11", 111: "f12",
}
# And by the private-use character AppKit gives them instead (NSUpArrowFunctionKey...).
_FUNCTION_KEYS = {0xF700: "up", 0xF701: "down", 0xF702: "left", 0xF703: "right", 0xF728: "forward_delete",
                  0xF729: "home", 0xF72B: "end", 0xF72C: "page_up", 0xF72D: "page_down"}
_FUNCTION_KEYS.update({0xF704 + number: "f{}".format(number + 1) for number in range(20)})
_SPECIAL_CHARACTERS = {"\r": "return", "\n": "return", "\t": "tab", " ": "space", "\x08": "delete", "\x7f": "delete",
                       "\x1b": "escape", "\x03": "return"}
_SHIFT, _OPTION, _CONTROL, _NO_COMMAND = 1, 2, 4, 8  # kAXMenuItemModifier...


def _shortcut(character: Any, modifiers: Any, virtual_key: Any) -> Optional[str]:
    key: Optional[str] = None
    if isinstance(character, str) and character:
        if character in _SPECIAL_CHARACTERS:
            key = _SPECIAL_CHARACTERS[character]
        elif ord(character[0]) in _FUNCTION_KEYS:
            key = _FUNCTION_KEYS[ord(character[0])]
        elif character.isprintable():
            key = character.lower()
    if key is None and isinstance(virtual_key, int) and virtual_key in _VIRTUAL_KEYS:
        key = _VIRTUAL_KEYS[virtual_key]
    if key is None:
        return None
    flags = modifiers if isinstance(modifiers, int) else 0
    parts = [name for flag, name in ((_CONTROL, "ctrl"), (_OPTION, "option"), (_SHIFT, "shift")) if flags & flag]
    if not flags & _NO_COMMAND:
        parts.append("cmd")
    return "+".join(parts + [key])


def _menu_bar(app: Union[str, apps.App, None]) -> Tuple[apps.App, int, int]:
    """The app, its owned element and its owned menu bar."""
    _require_permission("read the menus")
    target = _app_of(app)
    application = _application(target.pid)
    status, bar = _copy(application, "AXMenuBar")
    if not bar:
        _cf.release(application)
        if status == _API_DISABLED:
            _check(status, "read the menus")
        raise MacOSError("{} has no menu bar to read".format(target.name or "the app"))
    return target, application, bar


def _menu_entries(menu: int, budget: _Budget) -> Iterator[Tuple[int, Dict[str, Any]]]:
    """The items of a menu bar or a menu, each borrowed with its fields: the separators left out."""
    for item in _owned_list(menu, "AXChildren"):
        try:
            if not budget.spend():
                return
            status, raw = _read_many(item, _MENU_ATTRIBUTES)
            try:
                fields = {name: _python(value) for name, value in raw.items() if name not in ("_array", "AXChildren")}
            finally:
                _cf.release(raw.get("_array"))
            title = _text(fields.get("AXTitle"))
            if status == _SUCCESS and title:
                yield item, fields
        finally:
            _cf.release(item)


def _submenu(item: int) -> Optional[int]:
    """The owned menu an item opens, if it opens one."""
    children = _owned_list(item, "AXChildren")
    menu = None
    for child in children:
        if menu is None and _role(child) == "AXMenu":
            menu = child
        else:
            _cf.release(child)
    return menu


def _walk_menu(menu: int, path: Tuple[str, ...], budget: _Budget, found: List[MenuItem]) -> None:
    for item, fields in _menu_entries(menu, budget):
        here = path + ((_text(fields.get("AXTitle")) or ""),)
        submenu = _submenu(item)
        if submenu is not None:
            with _cf.owned(submenu):
                if path:  # an item of a menu that opens another
                    found.append(MenuItem(here, fields.get("AXEnabled") is not False, False, None))
                _walk_menu(submenu, here, budget, found)
            continue
        found.append(
            MenuItem(
                path=here,
                enabled=fields.get("AXEnabled") is not False,
                checked=bool(_text(fields.get("AXMenuItemMarkChar"))),
                shortcut=_shortcut(
                    fields.get("AXMenuItemCmdChar"),
                    fields.get("AXMenuItemCmdModifiers"),
                    fields.get("AXMenuItemCmdVirtualKey"),
                ),
            )
        )


def menu_items(app: Union[str, apps.App, None] = None) -> "builtins.list[MenuItem]":
    """
    Return every item of an app's menus, the Apple menu included, menu by menu and top to bottom.

    ::

        for item in macos.ui.menu_items("Preview"):
            print(" > ".join(item.path), item.shortcut or "")   # File > Export as PDF…

    ``app`` works as in :func:`elements`: the app in front by default; it
    needn't be in front to be read. An app that fills a menu only when it
    opens (a list of recent files) shows that menu empty.
    """
    target, application, bar = _menu_bar(app)
    found: List[MenuItem] = []
    try:
        _walk_menu(bar, (), _Budget(), found)
    finally:
        _cf.release(bar)
        _cf.release(application)
    return found


def _same(title: str, wanted: str) -> bool:
    def plain(text: str) -> str:
        return text.replace("…", "...").casefold().strip().rstrip(".").strip()

    return plain(title) == plain(wanted)


def _parse_path(path: Union[str, Sequence[str]]) -> List[str]:
    parts = [part.strip() for part in path.split(">")] if isinstance(path, str) else [str(part).strip() for part in path]
    if len(parts) < 2 or not all(parts):
        raise ValueError(
            "path must name a menu and an item in it, as 'File > Save' or ['File', 'Save'], not {!r}".format(path)
        )
    return parts


def click_menu_item(path: Union[str, Sequence[str]], *, app: Union[str, apps.App, None] = None) -> None:
    """
    Choose an item of an app's menus, as a click on it would: ``"File > Export as PDF…"``.

    ::

        macos.ui.click_menu_item("View > Show Sidebar", app="Finder")
        macos.ui.click_menu_item(["Format", "Font", "Bold"], app="TextEdit")

    ``path`` names the menu, then the item, through any submenus, as
    :attr:`MenuItem.path` gives it; ``"..."`` stands for ``"…"``, and case
    is ignored. The app (the one in front by default) comes to the front
    first, since its menus act on its window in front. Raises
    :class:`LookupError`, naming the items there are, when one isn't found,
    and :class:`~macos.errors.MacOSError` when it's dimmed.
    """
    parts = _parse_path(path)
    target, application, bar = _menu_bar(app)
    try:
        menu, owned_menu = bar, False
        budget = _Budget()
        for depth, wanted in enumerate(parts):
            match = None
            titles = []
            for item, fields in _menu_entries(menu, budget):
                title = _text(fields.get("AXTitle")) or ""
                titles.append(title)
                if _same(title, wanted):
                    match = (_cf.retain(item), fields)
                    break
            if owned_menu:
                _cf.release(menu)
            if match is None:
                where = " > ".join(parts[:depth]) or "the menu bar"
                raise LookupError(
                    "{} has no {!r} in {}: there's {}".format(
                        target.name or "the app", wanted, where, ", ".join(repr(title) for title in titles) or "nothing"
                    )
                )
            item, fields = match
            if depth == len(parts) - 1:
                with _cf.owned(item):
                    if fields.get("AXEnabled") is False:
                        raise MacOSError("{} is dimmed: it can't be chosen now".format(" > ".join(parts)))
                    _bring_to_front(target.pid)
                    with _cf.owned(_cf.string("AXPress")) as press:
                        _check(_ax().AXUIElementPerformAction(item, press), "choose {}".format(" > ".join(parts)))
                return
            with _cf.owned(item):
                submenu = _submenu(item)
            if submenu is None:
                raise LookupError("{} opens no menu: {} can't be in it".format(" > ".join(parts[: depth + 1]), parts[depth + 1]))
            menu, owned_menu = submenu, True
    finally:
        _cf.release(bar)
        _cf.release(application)
