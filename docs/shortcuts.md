# Shortcuts

{mod}`macos.shortcuts` runs the shortcuts you built in the Shortcuts app, so
anything they automate becomes available from Python.

```python
import macos

macos.shortcuts.list()                 # ['Resize Image', 'Translate', ...]
macos.shortcuts.run("Translate", input="Hola, mundo")  # 'Hello, world'
```

## Input

What you pass as `input` becomes the shortcut's *Shortcut Input*:

- a `str` is passed as **text**;
- a {class}`pathlib.Path`, or a list of paths (each a `Path` or a `str`), is
  passed as **files**.

```python
from pathlib import Path

macos.shortcuts.run("Translate", input="Bom dia")
macos.shortcuts.run("Resize Image", input=Path("photo.jpg"))
macos.shortcuts.run("Make GIF", input=[Path("a.png"), Path("b.png")])
```

A plain string on its own is always text, even if it looks like a path: wrap a
single file name in `Path(...)`.

## Output

{func}`~macos.shortcuts.run` returns the shortcut's text output, or `None` if
it produced none. When the shortcut outputs a file (an image, a PDF...), pass
`output` to save it; `run` then returns `None`:

```python
macos.shortcuts.run("Make GIF", input=[Path("a.png"), Path("b.png")], output="animation.gif")
```

`timeout` stops a shortcut still running after that many seconds (one stuck
on a prompt, say) and raises {class}`~macos.errors.CommandTimeoutError`:

```python
macos.shortcuts.run("Backup Notes", timeout=60)
```

Names are passed as names: a shortcut called `--help` runs that shortcut, it
doesn't print the command's usage.

## Listing shortcuts

```python
macos.shortcuts.list()                  # every shortcut
macos.shortcuts.list(folder="Work")     # only the ones in a folder
```

## Errors

A name that matches no shortcut raises {class}`~macos.ShortcutNotFoundError`
(also a `LookupError`). A shortcut that fails while running raises
{class}`~macos.CommandError` with the message from Shortcuts in `stderr`.

Running shortcuts needs macOS 12 or later.

## Reference

- {func}`macos.shortcuts.run`
- {func}`macos.shortcuts.list`
- {class}`macos.ShortcutNotFoundError`
