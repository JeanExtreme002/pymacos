# Dock

{mod}`macos.dock` configures the Dock: hide it, size it, move it, and choose
the apps kept in it. Handy to set up a new Mac from a script.

```python
import macos

macos.dock.set_autohide(True)
macos.dock.set_size(48)            # icons of 48 points
macos.dock.set_position("left")
macos.dock.add_app("Visual Studio Code")
macos.dock.remove_app("Podcasts")
```

Each change restarts the Dock to apply it ({func}`~macos.dock.restart` does it
by hand): it disappears for a second. To make several changes with one
restart, put them in a {func}`~macos.settings.batch` block
({func}`~macos.settings.apply` does that by itself):

```python
with macos.settings.batch():
    macos.dock.set_autohide(True)
    macos.dock.set_size(48)
    macos.dock.set_position("left")   # the Dock restarts once, here
```

No permission is needed.

## Settings

| Read | Change | Values |
|---|---|---|
| {func}`~macos.dock.autohide` | {func}`~macos.dock.set_autohide` | `True` hides it until the pointer reaches the edge |
| {func}`~macos.dock.size` | {func}`~macos.dock.set_size` | 16 to 128 points, like the Size slider |
| {func}`~macos.dock.position` | {func}`~macos.dock.set_position` | `"left"`, `"bottom"` or `"right"` |
| {func}`~macos.dock.autohide_delay` | {func}`~macos.dock.set_autohide_delay` | seconds a hidden Dock waits to show; `0` shows it at once |
| {func}`~macos.dock.magnification` | {func}`~macos.dock.set_magnification` | the size icons grow to under the pointer, or `None` |
| {func}`~macos.dock.show_recents` | {func}`~macos.dock.set_show_recents` | recent apps in their own section |
| {func}`~macos.dock.minimize_effect` | {func}`~macos.dock.set_minimize_effect` | `"genie"` or `"scale"` |
| {func}`~macos.dock.autohide_duration` | {func}`~macos.dock.set_autohide_duration` | seconds a hidden Dock takes to slide in; `0` has no animation, `None` is macOS's own |
| {func}`~macos.dock.show_indicators` | {func}`~macos.dock.set_show_indicators` | a dot under the open apps |
| {func}`~macos.dock.dim_hidden_apps` | {func}`~macos.dock.set_dim_hidden_apps` | translucent icons for hidden apps (⌘H) |
| {func}`~macos.dock.only_open_apps` | {func}`~macos.dock.set_only_open_apps` | only the open apps, like a taskbar |
| {func}`~macos.dock.launch_animation` | {func}`~macos.dock.set_launch_animation` | the icon bouncing while an app opens |
| {func}`~macos.dock.minimize_to_app` | {func}`~macos.dock.set_minimize_to_app` | `True` minimizes windows into their app's icon |

## Hot corners

{func}`~macos.dock.set_hot_corner` makes moving the pointer into a corner of
the screen do something, like System Settings › Desktop & Dock › Hot Corners:

```python
macos.dock.set_hot_corner("bottom_right", "lock_screen")
macos.dock.set_hot_corner("top_left", None)   # nothing
macos.dock.hot_corners()   # {'top_left': None, 'top_right': 'notification_center', ...}
```

The corners are `"top_left"`, `"top_right"`, `"bottom_left"` and
`"bottom_right"`; the actions, in {data}`~macos.dock.HOT_CORNER_ACTIONS`:
`"mission_control"`, `"app_windows"`, `"desktop"`, `"notification_center"`,
`"launchpad"`, `"quick_note"`, `"start_screensaver"`, `"disable_screensaver"`,
`"display_sleep"` and `"lock_screen"`.

`modifier` makes a corner wait for keys held down, so it doesn't fire by
accident:

```python
macos.dock.set_hot_corner("top_left", "mission_control", modifier="cmd")
macos.dock.hot_corner_modifiers()   # {'top_left': 'cmd', 'top_right': None, ...}
```

## Apps in the Dock

{func}`~macos.dock.apps` lists the apps kept in the Dock, in order, as
{class}`~macos.dock.DockApp` objects with their `name`, `path` and `bundle_id`.
Finder, always first, isn't listed, nor are the running apps that aren't kept.

```python
[app.name for app in macos.dock.apps()]   # ['Safari', 'Mail', 'Music', ...]

macos.dock.add_app("Terminal", index=0)   # first, right after Finder
macos.dock.remove_app("com.apple.Maps")   # by name, bundle ID or path
```

{func}`~macos.dock.add_app` finds the app as {func}`macos.apps.open` does,
raising {class}`~macos.AppNotFoundError` when it isn't installed, and doesn't
add it twice. {func}`~macos.dock.remove_app` takes it out of the Dock and
returns whether it was there; the app stays installed.

Blank spaces group the apps: {func}`~macos.dock.add_spacer` adds one, at the
end or before the app at `index`, and {func}`~macos.dock.remove_spacers`
takes them all out:

```python
macos.dock.add_spacer(index=3)
macos.dock.add_spacer(small=True)
macos.dock.remove_spacers()   # 2
```

## Folders

{func}`~macos.dock.add_folder` keeps a folder next to the Trash (an app
bundle is refused: that's {func}`~macos.dock.add_app`'s). `display` is
its icon, a `"stack"` of its items (the default) or the `"folder"`; `view` is
how it opens, `"automatic"` (the default), `"fan"`, `"grid"` or `"list"`; and
`sort` orders its items by `"name"`, `"date_added"` (the default),
`"date_modified"`, `"date_created"` or `"kind"`:

```python
macos.dock.add_folder("~/Downloads", view="grid", sort="date_added")
macos.dock.add_folder("~/Projects", display="folder", sort="name")

[folder.name for folder in macos.dock.folders()]   # ['Downloads', 'Projects']

macos.dock.remove_folder("~/Projects")
```

An entry of the Dock's preferences that isn't a tile (edited by hand, or by
another tool) is left out of {func}`~macos.dock.apps` and
{func}`~macos.dock.folders` with a `RuntimeWarning`, and a change made here
writes the list back without it.

A folder kept already is updated. Each {class}`~macos.dock.DockFolder` has its
`name`, `path`, `view`, `sort` and `display`.

## Spaces

Mission Control's settings live with the Dock's:

```python
macos.dock.set_auto_rearrange_spaces(False)        # keep the spaces where you put them
macos.dock.set_separate_spaces_per_display(False)  # one set of spaces across the displays
macos.dock.set_group_windows_by_app(True)          # Mission Control groups each app's windows
macos.dock.set_switch_to_space_with_app(False)     # ⌘Tab doesn't jump to another space
```

The second takes effect at the next login.

## Reference

- {func}`macos.dock.autohide`
- {func}`macos.dock.set_autohide`
- {func}`macos.dock.size`
- {func}`macos.dock.set_size`
- {func}`macos.dock.position`
- {func}`macos.dock.set_position`
- {func}`macos.dock.apps`
- {func}`macos.dock.add_app`
- {func}`macos.dock.remove_app`
- {func}`macos.dock.restart`
- {class}`macos.dock.DockApp`
- {data}`macos.dock.HOT_CORNER_ACTIONS`
- {func}`macos.dock.hot_corners`
- {func}`macos.dock.set_hot_corner`
- {func}`macos.dock.autohide_delay`
- {func}`macos.dock.set_autohide_delay`
- {func}`macos.dock.magnification`
- {func}`macos.dock.set_magnification`
- {func}`macos.dock.show_recents`
- {func}`macos.dock.set_show_recents`
- {func}`macos.dock.minimize_effect`
- {func}`macos.dock.set_minimize_effect`
- {func}`macos.dock.show_indicators`
- {func}`macos.dock.set_show_indicators`
- {func}`macos.dock.minimize_to_app`
- {func}`macos.dock.set_minimize_to_app`
- {func}`macos.dock.autohide_duration`
- {func}`macos.dock.set_autohide_duration`
- {func}`macos.dock.add_spacer`
- {func}`macos.dock.remove_spacers`
- {func}`macos.dock.auto_rearrange_spaces`
- {func}`macos.dock.set_auto_rearrange_spaces`
- {func}`macos.dock.separate_spaces_per_display`
- {func}`macos.dock.set_separate_spaces_per_display`
- {func}`macos.dock.hot_corner_modifiers`
- {func}`macos.dock.dim_hidden_apps`
- {func}`macos.dock.set_dim_hidden_apps`
- {func}`macos.dock.only_open_apps`
- {func}`macos.dock.set_only_open_apps`
- {func}`macos.dock.launch_animation`
- {func}`macos.dock.set_launch_animation`
- {func}`macos.dock.group_windows_by_app`
- {func}`macos.dock.set_group_windows_by_app`
- {func}`macos.dock.switch_to_space_with_app`
- {func}`macos.dock.set_switch_to_space_with_app`
- {class}`macos.dock.DockFolder`
- {func}`macos.dock.folders`
- {func}`macos.dock.add_folder`
- {func}`macos.dock.remove_folder`
