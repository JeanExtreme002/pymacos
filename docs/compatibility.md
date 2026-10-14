# Threads and macOS internals

Two things to know before building on pymacos: which calls must run on the
main thread, and which features rest on parts of macOS that Apple doesn't
document, so a macOS update may change them.

## The main thread

Most of the package works from any thread. A few of Apple's frameworks only
work on the main thread, the one that runs your script; elsewhere they would
hang or crash the process, so these calls check first and raise
{class}`~macos.MacOSError` from a worker thread:

| Calls | Why |
|---|---|
| {func}`macos.events.run`, {func}`macos.events.wait` | macOS delivers these notifications on the main thread's run loop |
| {func}`macos.camera.photo`, {func}`macos.camera.record` | the camera answers on the main queue, which only the main thread serves |
| {func}`macos.maps.geocode`, {func}`~macos.maps.reverse_geocode` | the geocoder answers on the main queue |
| {mod}`macos.menubar`: creating an item, adding entries, {func}`~macos.menubar.run` | AppKit draws the menu bar from the main thread |
| {func}`macos.document.text` and {func}`~macos.document.convert` on HTML or a web archive, and conversions to PDF | WebKit and AppKit's text views |
| {func}`macos.keyboard.layouts`, {func}`~macos.keyboard.layout`, {func}`~macos.keyboard.set_layout` | Text Input Sources |

Callbacks run on the thread that waits for them: {func}`macos.hotkeys.run`
and {func}`macos.events.run` call yours one at a time on the calling thread,
and {func}`macos.keyboard.watch`, {func}`macos.mouse.watch` and
{func}`macos.clipboard.watch` hand their events to the loop that iterates
them. Loop on the thread that called them. The microphone
({func}`macos.audio.record`) works from any thread, unlike the camera.

What a thread holds is its own: the keys {func}`macos.keyboard.hold` holds
down, and the restarts {func}`macos.settings.batch` puts off, apply to the
thread that started them. A Ctrl-C while native code runs (a run loop, a
sound analysis) is held until that code ends, then raised as usual, so a
listener stops cleanly.

## Features on macOS internals

Everything else uses Apple's public frameworks and commands. The features
below read or write what Apple doesn't document: a private framework, a
setting System Settings writes but no API exposes, or the text a command
prints. They work on the macOS versions the test suite runs on (the current
one and the previous, every week), and a macOS release may change them. When a
private symbol is gone, the call raises {class}`~macos.NotSupportedError`; a
setting macOS stopped reading would fail silently, the getter still reporting
what was written.

| Feature | Rests on |
|---|---|
| {func}`macos.screen.brightness`, {func}`~macos.screen.set_brightness` | the private DisplayServices framework |
| Night Shift and True Tone ({func}`macos.screen.night_shift`, {func}`~macos.screen.set_night_shift`, {func}`~macos.screen.set_night_shift_schedule`, {func}`~macos.screen.true_tone`...) | the private CoreBrightness framework |
| {func}`macos.screen.lock` | the private login framework |
| The keyboard backlight ({func}`macos.keyboard.brightness`, {func}`~macos.keyboard.set_brightness`, {func}`~macos.keyboard.auto_brightness`) | the private CoreBrightness framework |
| {func}`macos.bluetooth.power`, {func}`~macos.bluetooth.set_power` | private functions of IOBluetooth |
| {meth}`Window.screenshot() <macos.windows.Window.screenshot>` | a private Accessibility function, to tell `screencapture` which window |
| System keyboard shortcuts ({func}`macos.keyboard.system_shortcuts`...) | the shortcut numbers in `com.apple.symbolichotkeys` |
| Menu bar items, the battery percentage and the clock ({func}`macos.system.menu_bar_items`, {func}`~macos.system.set_menu_bar_items`, {func}`~macos.system.set_show_battery_percentage`, {func}`~macos.system.set_clock_format`) | Control Center's and the clock's preference keys, and restarting Control Center |
| {func}`macos.system.startup_items` | the text `launchctl print` writes, which Apple says may change |
| {func}`macos.system.gpu_usage`, {func}`~macos.system.lid_closed` | properties of the graphics drivers and the lid in the IOKit registry |
| Battery health ({func}`macos.power.battery`) | properties of the battery's IOKit service |
| Window tiling settings ({func}`macos.windows.tiling`...) | the window manager's preference keys, and restarting it |
| The Dock's, Finder's, the trackpad's, the mouse's, the menu bar's and the sound effects' settings ({mod}`macos.dock`, {mod}`macos.finder`, {mod}`macos.trackpad`, {mod}`macos.mouse`, {mod}`macos.appearance`, {mod}`macos.sound`) | the preference keys System Settings writes, and restarting the Dock, Finder or SystemUIServer |

The release notes on [GitHub Releases](https://github.com/JeanExtreme002/pymacos/releases)
are the changelog: a feature that a macOS release changed is fixed there, and
listed.
