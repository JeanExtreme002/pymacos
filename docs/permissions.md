# Permissions

macOS protects some features behind privacy permissions. They are granted to
the **app running Python** (Terminal, iTerm, VS Code, PyCharm...), not to Python
itself, so a script can work in one terminal and not in another.

| Feature | Permission | Where to enable it |
|---|---|---|
| {func}`macos.screenshot` | Screen Recording | System Settings › Privacy & Security › Screen & System Audio Recording |
| {func}`macos.notify` | Notifications for *Script Editor* | System Settings › Notifications › Script Editor |
| {mod}`macos.keyboard` typing and keys, {mod}`macos.mouse` moving, clicking and scrolling | Accessibility | System Settings › Privacy & Security › Accessibility |
| {func}`macos.camera.photo`, {func}`macos.camera.record` | Camera (asked the first time) | System Settings › Privacy & Security › Camera |
| {func}`macos.audio.record`, {func}`~macos.audio.record_until_silence`, {func}`~macos.audio.input_level`, videos with sound | Microphone (asked the first time) | System Settings › Privacy & Security › Microphone |
| {mod}`macos.windows` | Accessibility | System Settings › Privacy & Security › Accessibility |
| {mod}`macos.hotkeys` | Input Monitoring, and Accessibility to keep shortcuts from the app in front | System Settings › Privacy & Security › Input Monitoring |
| {func}`macos.screen.record` | Screen Recording (and Microphone with `audio=True`) | System Settings › Privacy & Security › Screen & System Audio Recording |
| {func}`macos.screen.find_text`, {func}`~macos.screen.wait_for_text`, {func}`~macos.screen.color_at`, {meth}`Window.screenshot() <macos.windows.Window.screenshot>` | Screen Recording | System Settings › Privacy & Security › Screen & System Audio Recording |
| {func}`macos.mouse.click_text` | Screen Recording and Accessibility | System Settings › Privacy & Security |
| {func}`macos.keyboard.watch`, {func}`macos.mouse.watch` | Input Monitoring | System Settings › Privacy & Security › Input Monitoring |
| {func}`macos.finder.selection`, {func}`~macos.finder.current_folder` | Automation of Finder (asked the first time) | System Settings › Privacy & Security › Automation |
| {func}`macos.apps.login_items`, {func}`~macos.apps.add_login_item`, {func}`~macos.apps.remove_login_item` | Automation of *System Events* (asked the first time) | System Settings › Privacy & Security › Automation |
| {func}`macos.time_machine.last_backup` | may need Full Disk Access | System Settings › Privacy & Security › Full Disk Access |
| {mod}`macos.music` | Automation of Music or Spotify (asked the first time) | System Settings › Privacy & Security › Automation |
| {mod}`macos.browser` | Automation of the browser (asked the first time); {func}`~macos.browser.run_js` also needs the browser's *Allow JavaScript from Apple Events* | System Settings › Privacy & Security › Automation |
| {func}`macos.screen.set_night_shift_schedule` with `"sunset"` | Location Services | System Settings › Privacy & Security › Location Services |
| {func}`macos.appearance.set_mode` | Automation of *System Events* (asked the first time) | System Settings › Privacy & Security › Automation |
| {func}`macos.bluetooth.connect`, {func}`~macos.bluetooth.disconnect`, {func}`~macos.bluetooth.set_power` | Bluetooth (may be asked the first time) | System Settings › Privacy & Security › Bluetooth |

The other features (clipboard, appearance, apps, Keychain, speech, power,
Shortcuts, Finder, volume, Spotlight, geocoding, dialogs, system info, Vision, images,
PDFs, language, audio devices, sounds, network, brightness, the keyboard
backlight, the mouse position, listing Bluetooth devices, Caps Lock, microphone
volume, camera and microphone use, locking the screen, system events, scheduling
scripts, the Dock, defaults, Finder and screenshot settings, disk images,
Touch ID) need no permission. Watching folders needs none either, except that
the Desktop, Documents and Downloads folders ask for access the first time,
like any access to them.

## Screen Recording

Without this permission macOS doesn't fail: it returns a screenshot that shows
only the wallpaper and the menu bar. `pymacos` checks first and raises
{class}`~macos.PermissionDeniedError` instead.

```python
macos.screen.has_permission()       # check without prompting
macos.screen.request_permission()   # show the system prompt
```

After granting it in System Settings, **restart the app running Python**; macOS
only applies the change to newly started processes.

## Camera and microphone

The camera and the microphone need their own permission, which macOS asks for
the first time a script uses them. Check or ask without taking anything:

```python
macos.camera.has_permission()
macos.camera.request_permission()   # shows the prompt the first time
macos.audio.has_permission()        # the microphone
macos.audio.request_permission()
```

If the user denies it, {mod}`macos.camera`, {func}`macos.audio.record`,
{func}`~macos.audio.record_until_silence` and {func}`~macos.audio.input_level` raise
{class}`~macos.PermissionDeniedError`; allow it again in System Settings ›
Privacy & Security, then restart the app running Python. If the prompt is left
unanswered until the time runs out, they raise {class}`~macos.PromptTimeoutError`
instead: run the call again and answer it.

## Accessibility

Sending keystrokes and mouse events lets a script control any app, so macOS
asks for the Accessibility permission. Without it macOS silently drops the
events; {mod}`macos.keyboard` and {mod}`macos.mouse` check first and raise
{class}`~macos.PermissionDeniedError` instead.

```python
macos.keyboard.has_permission()       # check without prompting (the same for macos.mouse)
macos.keyboard.request_permission()   # show the system prompt
```

As with Screen Recording, **restart the app running Python** after allowing it.

## Input Monitoring

{mod}`macos.hotkeys` listens to the keyboard for its shortcuts, which macOS
treats as Input Monitoring; keeping a shortcut from the app in front also
needs Accessibility. Without them, {func}`~macos.hotkeys.run` and
{func}`~macos.hotkeys.wait` raise {class}`~macos.PermissionDeniedError`.

```python
macos.hotkeys.has_permission()       # check without prompting
macos.hotkeys.request_permission()   # show the system prompt
```

Restart the app running Python after allowing it.

## Automation

{func}`macos.appearance.set_mode` asks System Events to switch the
appearance, {func}`macos.apps.login_items` asks it for the login items,
{func}`macos.finder.selection` asks Finder for the selected files,
{mod}`macos.music` asks Music or Spotify to play, and {mod}`macos.browser`
asks the browser for its tabs, so the first time macOS asks whether the app
running Python may control them. If that's denied, it raises
{class}`~macos.PermissionDeniedError`; allow it again in System Settings ›
Privacy & Security › Automation.

## Notifications

Notifications are posted through AppleScript, so macOS attributes them to *Script Editor*.

When notifications for Script Editor are turned off, macOS drops them without
an error, so {func}`macos.notify` raises {class}`~macos.PermissionDeniedError`
instead. Turn them on in System Settings › Notifications › Script Editor. If
Script Editor isn't listed there yet, open Script Editor, run
`display notification "hi"` once and accept the prompt.

Also check that a Focus mode (such as Do Not Disturb) isn't hiding them.

## Keychain

Reading an item that another app created may make macOS ask the user to allow
access. If the user denies it, {mod}`macos.keychain` raises
{class}`~macos.PermissionDeniedError`. Items created by your script can be read
back by it without a prompt.
