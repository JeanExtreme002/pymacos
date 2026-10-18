# Errors

The errors that come from macOS derive from {class}`~macos.MacOSError`, so a
single `except` catches them all:

```python
try:
    macos.screenshot("screen.png")
except macos.MacOSError as error:
    print("macOS said no:", error)
```

Where a builtin exception means the same thing, the `pymacos` exception also
subclasses it, so existing handlers keep working: `except PermissionError`
catches {class}`~macos.PermissionDeniedError`, and `except LookupError` catches
{class}`~macos.AppNotFoundError`.

| Exception | Raised when |
|---|---|
| {class}`~macos.NotSupportedError` | Not running on macOS, or a required system tool is missing |
| {class}`~macos.PermissionDeniedError` | A privacy permission is missing, or the user denied access |
| {class}`~macos.MainThreadError` | A call that only works on the main thread (the camera, the menu bar, the geocoder, keyboard layouts, `events.run()`, documents) was made from another thread (also a `RuntimeError`); see [Threads](compatibility.md) |
| {class}`~macos.PromptTimeoutError` | A camera or microphone permission prompt went unanswered (also a `TimeoutError`) |
| {class}`~macos.WaitTimeoutError` | What was waited for (a copy, an appearance change, a geocoding answer, a folder walked, a Bluetooth or VPN switch, the Dock restarting, a default app's confirmation, a window's full-screen change, a video export, a webcam photo or video) didn't happen in time (also a `TimeoutError`) |
| {class}`~macos.AppNotFoundError` | No app matches the name |
| {class}`~macos.AppLaunchTimeoutError` | An app was launched but didn't show up in time (also an {class}`~macos.AppNotFoundError` and a `TimeoutError`) |
| {class}`~macos.ShortcutNotFoundError` | No shortcut has the name (also a `LookupError` and a `CommandError`) |
| {class}`~macos.KeychainError` | The Keychain returned an error (see its `status`) |
| {class}`~macos.CommandError` | A system command failed, or was killed by a signal (see its `cmd`, `returncode`, negative for a signal, and `stderr`; `str()` and `repr()` name the command only, since its arguments may hold a URL with a token or a dialog's text, but show `stderr` as the command wrote it, which may quote them) |
| {class}`~macos.CommandTimeoutError` | A system command didn't finish in time and was stopped (also a `TimeoutError`; see its `cmd` and `timeout`: `str()` and `repr()` name the command only) |
| {class}`~macos.MacOSError` | Any other failure macOS reports, such as a page that can't be drawn |

Mistakes in the call, and problems with files, raise the usual builtin
exceptions instead:

| Exception | Raised when |
|---|---|
| `ValueError` | An invalid argument, such as an unsupported screenshot format |
| `TypeError` | An argument of the wrong type, such as a volume that isn't an `int` |
| `FileNotFoundError` | An input file or folder doesn't exist |
| `FileExistsError` | The destination already exists |
| `NotADirectoryError` | A folder was expected, but the path is a file |
| `IsADirectoryError` | A file was expected (an input or an output), but the path is a folder |
| `TimeoutError` | Caught by `except TimeoutError`: every wait that ran out of time raises a subclass of it ({class}`~macos.WaitTimeoutError`, {class}`~macos.CommandTimeoutError`, {class}`~macos.PromptTimeoutError`, {class}`~macos.AppLaunchTimeoutError`) |
| `OSError` | A file's attributes can't be read or changed |
| `PermissionError` | A file the app isn't allowed to read (its permissions, or a folder such as Desktop without access) |
| `ProcessLookupError`, `PermissionError` | {func}`macos.system.kill` on a process that's gone, or another user's |

## Reference

- [Exceptions in the API reference](api.md#exceptions)
