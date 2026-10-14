# Why pymacos?

Showing a notification, reading the clipboard or checking for Dark mode from
Python usually means shelling out to `osascript`, remembering `defaults` keys,
or pulling in PyObjC and learning Cocoa. `pymacos` gives you one small, typed API
instead.

## Before and after

Without `pymacos`:

```python
import subprocess
from AppKit import NSPasteboard, NSPasteboardTypeString  # pip install pyobjc

# A notification: AppleScript inside a Python string. A quote in the
# message breaks it.
subprocess.run(
    ["osascript", "-e", 'display notification "Build finished" with title "CI"']
)

# The clipboard: Cocoa selectors through PyObjC.
pasteboard = NSPasteboard.generalPasteboard()
pasteboard.clearContents()
pasteboard.setString_forType_("hello", NSPasteboardTypeString)

# Dark mode: a preferences key you have to know, read by a command whose
# failure also means "Light mode".
result = subprocess.run(
    ["defaults", "read", "-g", "AppleInterfaceStyle"], capture_output=True, text=True
)
is_dark = result.stdout.strip() == "Dark"
```

With `pymacos`:

```python
import macos

macos.notify("Build finished", title="CI")
macos.clipboard.copy("hello")
is_dark = macos.appearance.is_dark()
```

## What you get

### No dependencies

`pip install pymacos` installs nothing else and compiles nothing. Native features
call the system frameworks through
[ctypes](https://docs.python.org/3/library/ctypes.html); the rest wraps tools
that ship with every Mac.

### A Pythonic API

Plain functions, dataclasses and real exceptions, with type hints throughout.
No Objective-C selectors, no parsing command output, no exit codes.

### Safe by default

Your text is never pasted into shell or AppleScript source, so quotes,
backslashes or a message starting with `-` can't break a call or inject code.
The commands it runs are macOS's own, from `/usr/bin` and its siblings, never
a program of the same name found earlier in your `PATH`.
Passwords go straight to the Keychain and never show up in the process list.

### Errors that explain themselves

macOS often fails silently: a screenshot taken without the Screen Recording
permission just comes back mostly empty. `pymacos` checks first and raises
{class}`~macos.PermissionDeniedError`, saying which permission is missing and
where to turn it on. The errors that come from macOS derive from
{class}`~macos.MacOSError`; invalid arguments and missing files raise the
usual `ValueError` or `FileNotFoundError`. See [Errors](errors.md).
