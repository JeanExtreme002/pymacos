# Notifications

Post a notification to Notification Center with {func}`macos.notify`:

```python
import macos

macos.notify("Build finished")
```

Add a title, a subtitle and a sound:

```python
macos.notify("3 tests failed", title="CI", subtitle="main", sound="Basso")
```

`sound` is the name of a system alert sound, such as `"Basso"`, `"Glass"`,
`"Ping"` or `"Submarine"`. {func}`macos.sound.names` lists them all, and only
those are accepted (in any case): any other name raises `ValueError`, since
macOS would post the notification without a sound and no error.

Text longer than 4096 characters is clipped, ending in "…": Notification
Center shows a few lines at most. Text with a NUL character or a lone
surrogate can't be passed to `osascript` and raises `ValueError`.

## Getting notified when a script finishes

```python
import macos

def main():
    ...

try:
    main()
except Exception as error:
    macos.notify(str(error), title="Script failed", sound="Basso")
    raise
else:
    macos.notify("All done", title="Script finished", sound="Glass")
```

## How it works

The notification is posted through AppleScript's `display notification`. The
native API (`UNUserNotificationCenter`) only works from a signed app bundle,
which a Python script isn't. The text is passed to AppleScript as arguments,
never pasted into the script source, so quotes or backslashes in it are safe.

Because of this, macOS shows the notification as coming from *Script Editor*.

## When notifications are turned off

If notifications are turned off for Script Editor, macOS drops them without any
error. {func}`macos.notify` checks that setting first (and right after the very
first notification, which turns it on or off) and raises
{class}`~macos.PermissionDeniedError` instead, saying where to turn them on. See
[Permissions](permissions.md#notifications).

{func}`macos.notifications.is_allowed` tells you in advance: `True`, `False`,
or `None` when it can't tell yet (Script Editor has never posted a
notification). Pass `check_permission=False` to {func}`macos.notify` to skip
the check.

The setting is read from an undocumented macOS format, so the check is best
effort: if it can't be read, the notification is posted as usual. Focus modes
such as Do Not Disturb can still hide allowed notifications.

## Reference

- {func}`macos.notify`
- {func}`macos.notifications.is_allowed`
