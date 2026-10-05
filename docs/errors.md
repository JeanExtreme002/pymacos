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
| {class}`~macos.PromptTimeoutError` | A camera or microphone permission prompt went unanswered (also a `TimeoutError`) |
| {class}`~macos.AppNotFoundError` | No app matches the name, or it didn't start in time |
| {class}`~macos.ShortcutNotFoundError` | No shortcut has the name (also a `LookupError` and a `CommandError`) |
| {class}`~macos.KeychainError` | The Keychain returned an error (see its `status`) |
| {class}`~macos.CommandError` | A system command failed (see its `cmd`, `returncode` and `stderr`) |
| {class}`~macos.CommandTimeoutError` | A system command didn't finish in time and was stopped (also a `TimeoutError`) |
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
| `TimeoutError` | A wait ran out of time, such as {func}`macos.clipboard.wait_for_change` |
| `OSError` | A file's attributes can't be read or changed |
| `ProcessLookupError`, `PermissionError` | {func}`macos.system.kill` on a process that's gone, or another user's |

## Reference

- [Exceptions in the API reference](api.md#exceptions)
