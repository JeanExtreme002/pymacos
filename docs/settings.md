# Settings

{mod}`macos.settings` saves this Mac's settings to a JSON file and applies
them to another Mac: dotfiles for macOS, without a line of `defaults write`.

```python
import json
import macos

json.dump(macos.settings.export(), open("my-mac.json", "w"), indent=2)

# on the new Mac:
macos.settings.apply(json.load(open("my-mac.json")))
```

## Exporting

{func}`~macos.settings.export` reads the settings this package knows, by
section: `keyboard`, `trackpad`, `mouse`, `dock`, `finder`,
`windows`, `appearance`, `screen` (screenshots, screen saver and Night Shift),
`sound` and `system`:

```text
{
  "dock": {"autohide": true, "size": 48, "position": "left", "hot_corners": {"top_left": {"action": "mission_control", "modifier": null}, ...}},
  "finder": {"show_extensions": true, "default_view": "columns", ...},
  "keyboard": {"key_repeat": [0.03, 0.225], "press_and_hold": false, ...},
  ...
}
```

It's plain JSON, to keep in a repository and edit by hand.
{func}`~macos.settings.names` lists every setting, and settings this Mac
doesn't have (a keyboard backlight, Night Shift...) are left out.

## Applying

{func}`~macos.settings.apply` takes an export, or any part of one: the
settings left out stay as they are.

```python
macos.settings.apply({"dock": {"autohide": True, "size": 48}, "finder": {"show_extensions": True}})
# ['dock.autohide', 'dock.size']: finder.show_extensions was already on
```

It only changes the settings that differ, restarts the Dock and Finder once
at the end, and returns the names of those it changed. An unknown name or an
invalid value (a size out of range, an unknown hot corner action, a key that
can't be remapped) raises `ValueError` before anything changes, naming every
bad entry. If a change still fails midway (a missing permission, say), the
settings already changed are put back before the error is raised. Settings
this Mac doesn't have are skipped. Some settings wait for the next login, as
their own pages say.

Key remappings are swapped in as a whole: the new list replaces the old one in
one step, so a bad entry never leaves the keyboard without its remappings.

## Reference

- {func}`macos.settings.export`
- {func}`macos.settings.apply`
- {func}`macos.settings.names`
