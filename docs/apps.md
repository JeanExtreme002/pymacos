# Apps

{mod}`macos.apps` lists, opens, activates, quits and uninstalls applications.

## Listing running apps

```python
import macos

for app in macos.apps.running():
    print(app.name, app.bundle_id, app.pid)
```

By default {func}`~macos.apps.running` returns regular apps, the ones with a
Dock icon. Pass `include_background=True` to also get menu-bar extras, agents
and helper processes:

```python
macos.apps.running(include_background=True)
```

{func}`~macos.apps.frontmost` returns the app that has keyboard focus:

```python
macos.apps.frontmost()   # App(name='Safari', bundle_id='com.apple.Safari', ...)
```

## Finding an app

{func}`~macos.apps.get` finds a running app, or returns `None` if it isn't
running. It accepts any of these:

```python
macos.apps.get("Safari")                          # displayed name
macos.apps.get("com.apple.Safari")                # bundle identifier
macos.apps.get("Safari.app")                      # bundle file name
macos.apps.get("/Applications/Safari.app")        # path (symlinks are fine)
```

Names are compared case-insensitively, against both the displayed name and the
bundle's file name. So `"Calculator"` also finds the app on a Mac set to
Portuguese, where it is displayed as "Calculadora".

## Opening an app

{func}`~macos.apps.open` launches an app, or brings it to the front if it's
already running, and returns it once it's up:

```python
safari = macos.apps.open("Safari")
macos.apps.open("com.apple.Safari")
macos.apps.open("/Applications/Safari.app")
macos.apps.open("Mail", background=True)   # launch without stealing focus
```

It raises {class}`~macos.AppNotFoundError` if no installed app matches, or if
the app doesn't show up within `timeout` seconds (10 by default).

A name is only treated as a path when it contains a `/` (or starts with `~`),
so `open("Notes")` finds the Notes app even if the current directory has a
`Notes` folder. Use `open("./Notes.app")` for a bundle in the current
directory.

## Controlling an app

{func}`~macos.apps.running`, {func}`~macos.apps.frontmost`,
{func}`~macos.apps.get` and {func}`~macos.apps.open` return
{class}`~macos.apps.App` objects:

```python
app = macos.apps.get("Safari")

app.name, app.bundle_id, app.pid, app.path

app.is_running    # still running?
app.is_active     # frontmost?
app.is_hidden

app.activate()    # bring to the front; returns whether it is now frontmost
app.hide()
app.unhide()
```

## Quitting an app

{meth}`App.quit() <macos.apps.App.quit>` asks the app to quit, like choosing
*Quit* from its menu. The app may show a "save changes?" dialog, or refuse.

```python
app.quit()                    # returns right away
app.quit(timeout=5)           # waits up to 5 s; returns whether it exited
app.quit(force=True)          # like Force Quit: unsaved work is lost
```

For example, a small focus mode:

```python
for name in ("Slack", "Discord", "Mail"):
    app = macos.apps.get(name)

    if app is not None:
        app.quit()
```

## Opening files with an app

{func}`macos.open` opens a file, folder or URL with its default app, like
double-clicking it. {func}`macos.open_with` picks the app, like Finder's
*Open With*:

```python
macos.open("report.pdf")                  # in the default PDF app
macos.open("~/Downloads")                 # in Finder
macos.open("https://python.org")          # in the default browser

macos.open_with("report.pdf", "Preview")
macos.open_with("notes.md", "com.microsoft.VSCode")
```

The app can be a name, a bundle identifier or a path, as for
{func}`~macos.apps.open`. Pass `background=True` to open without bringing the
app to the front. A path that doesn't exist raises `FileNotFoundError`. An
app that isn't there raises {class}`~macos.AppNotFoundError`; one that's there
but won't open (damaged, blocked by Gatekeeper, for another processor) raises
{class}`~macos.CommandError`, with macOS's reason.

`macos.open` opens any kind of URL with whichever app claims it, and a file
that is an app or a script runs: don't hand it text from an untrusted source
as is. `schemes` limits it to some kinds of URL, and raises `ValueError` for
anything else; a file or folder counts as `"file"`:

```python
macos.open(link_from_a_web_page, schemes={"https", "http"})   # not a file, nor zoommtg://...
```

`macos.open` is not included in `from macos import *`, so it never replaces
Python's built-in `open()`.

## Default apps

```python
macos.apps.default_for("pdf")                 # '/System/Applications/Preview.app'
macos.apps.default_for("public.plain-text")   # '/System/Applications/TextEdit.app'
macos.apps.default_browser()                  # '/Applications/Safari.app'
```

{func}`~macos.apps.default_for` takes an extension (`"pdf"`, `".png"`,
`"tar.gz"`) or a type identifier (`"public.image"`), and returns `None` when no
app opens it. {func}`~macos.apps.set_default_for` changes it, like Get Info ›
Open with › Change All:

```python
macos.apps.set_default_for("md", "Visual Studio Code")
```

Since macOS 26, macOS asks the user to confirm the change, and the function
waits for the answer (`timeout`, one minute by default); it raises
{class}`~macos.MacOSError` when the change is declined or the answer doesn't
come. The default browser
can't be changed this way: macOS asks for that one in System Settings.

## Login items

{func}`~macos.apps.login_items` lists the apps that open when you log in, and
{func}`~macos.apps.add_login_item` and {func}`~macos.apps.remove_login_item`
change them:

```python
macos.apps.add_login_item("Rectangle")
[item.name for item in macos.apps.login_items()]   # ['Rectangle', ...]
macos.apps.remove_login_item("Rectangle")
```

They go through System Events, so the first time macOS asks to allow it
([Automation](permissions.md#automation)). Apps that register themselves as
background items, with their own switch in System Settings, aren't listed.

## Installing from a disk image

{func}`~macos.apps.install_from_dmg` installs the app a `.dmg` holds, as
dragging it to Applications does:

```python
macos.apps.install_from_dmg("~/Downloads/Rectangle.dmg")   # '/Applications/Rectangle.app'
```

It mounts the image, copies the `.app` into `destination` (`/Applications` by
default), and unmounts it. An app already installed raises `FileExistsError`,
unless `replace=True`. When the install fails and the image then won't
unmount either, the error raised is the install's. To mount an image
yourself, see {func}`macos.system.mount_image`.

## Downloaded apps

macOS marks what's downloaded from the internet, and checks it the first
time it opens; that mark is behind "is damaged and can't be opened".
{func}`~macos.apps.unquarantine` removes it from an app you trust, and
everything in it, like `xattr -dr com.apple.quarantine`:

```python
macos.apps.is_quarantined("/Applications/Tool.app")   # True
macos.apps.unquarantine("/Applications/Tool.app")     # 1204 files
```

## Threads

All functions work from any thread, not only the main one.

## Installed apps

{func}`~macos.apps.installed` lists the apps installed on this Mac, with their
version and bundle ID:

```python
{app.name: app.version for app in macos.apps.installed()}   # {'Safari': '18.6', 'Xcode': '16.2', ...}
```

It looks in the Applications folders (yours, the Mac's and the system's),
and at the apps Spotlight knows elsewhere.

## Uninstalling an app

Dragging an app to the Trash leaves its settings, caches and support files
behind, sometimes gigabytes of them. {func}`~macos.apps.uninstall` moves the
app to the Trash with the files it left in your Library, and returns what it
moved, the app first. `dry_run=True` only returns what would go:

```python
macos.apps.uninstall("Slack", dry_run=True)
# [PosixPath('/Applications/Slack.app'),
#  PosixPath('/Users/me/Library/Caches/com.tinyspeck.slackmacgap'),
#  PosixPath('/Users/me/Library/Preferences/com.tinyspeck.slackmacgap.plist'), ...]

macos.apps.uninstall("Slack")
```

The files are found by the app's bundle ID (in Application Support, Caches,
Containers, Preferences, Saved Application State, Logs, and the like), which
only that app uses. Files named after the ID of another installed app are
left alone, such as Chrome Canary's (`com.google.Chrome.canary`) when
uninstalling Chrome.

Many apps also keep a folder named after themselves, such as
`Application Support/Slack`. A name can be shared, though: Firefox Developer
Edition and Firefox Nightly keep their profiles in `Application Support/Firefox`
too. So those folders only go with `include_name_matches=True`, and even then a
name is skipped when another installed app's name holds it (or is held in it),
or when another app comes from the same maker. They come last in the list:
look at a dry run first.

```python
macos.apps.uninstall("Slack", dry_run=True, include_name_matches=True)[-1]
# PosixPath('/Users/me/Library/Application Support/Slack')
```

Everything goes to the Trash, so *Put Back* undoes it. Only your own files are
touched: `/Library`'s need an administrator.

It raises {class}`~macos.MacOSError` for an app that's running (quit it first;
a dry run works all the same) or that comes with macOS, like Safari, and
{class}`~macos.AppNotFoundError` for one that isn't installed. An app
installed for every user may need an administrator to be moved: then nothing
is moved, and the error says so.

## Reference

- {func}`macos.apps.running`
- {func}`macos.apps.frontmost`
- {func}`macos.apps.get`
- {func}`macos.apps.open`
- {class}`macos.apps.App`
- {func}`macos.open`
- {func}`macos.apps.open_with`
- {func}`macos.apps.default_for`
- {func}`macos.apps.default_browser`
- {func}`macos.apps.set_default_for`
- {func}`macos.apps.login_items`
- {func}`macos.apps.add_login_item`
- {func}`macos.apps.remove_login_item`
- {func}`macos.apps.install_from_dmg`
- {class}`macos.apps.LoginItem`
- {func}`macos.apps.is_quarantined`
- {func}`macos.apps.unquarantine`
- {class}`macos.apps.InstalledApp`
- {func}`macos.apps.installed`
- {func}`macos.apps.uninstall`
