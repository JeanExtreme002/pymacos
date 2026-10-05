# Dialogs

{mod}`macos.dialog` shows native macOS dialogs: alerts, yes/no questions, text
input, lists and file pickers. It's a way to talk to the user from a script
without a GUI toolkit such as tkinter.

```python
import macos

macos.dialog.alert("Backup finished", detail="12 files copied")

if macos.dialog.confirm("Delete the old logs?"):
    delete_logs()

name = macos.dialog.prompt("What's your name?")
```

Dialogs need no permission. They open in front of other windows and block
until the user answers.

## Alerts

```python
macos.dialog.alert("Upload failed")
macos.dialog.alert("Upload failed", detail="The server didn't answer.")
```

## Yes/no questions

{func}`~macos.dialog.confirm` returns `True` if the user clicks the OK button,
and `False` for the cancel button or Escape. Both buttons can be renamed:

```python
macos.dialog.confirm("Delete 3 files?", ok="Delete", cancel="Keep")
```

## Text input

{func}`~macos.dialog.prompt` returns the typed text, or `None` if the user
cancels:

```python
city = macos.dialog.prompt("City:", default="New York")
password = macos.dialog.prompt("Password:", hidden=True)   # shows dots
```

The text typed comes back on `osascript`'s output, never on a command line.
`default`, though, reaches the dialog as an argument, which other processes of
the same user can see in the process list while the dialog is open: don't
pre-fill a `hidden` prompt with a secret.

## Choosing from a list

```python
fruit = macos.dialog.choose(
    ["Apple", "Banana", "Pear"], prompt="Pick a fruit", default="Pear", title="Fruits"
)
```

{func}`~macos.dialog.choose` returns the chosen option, or `None` if cancelled.
{func}`~macos.dialog.confirm` and {func}`~macos.dialog.prompt` take a `title`
too.

## Picking files and folders

```python
report = macos.dialog.choose_file("Choose a report", types=["pdf"])
photos = macos.dialog.choose_files(types=["public.image"], folder="~/Pictures")
target = macos.dialog.choose_folder("Where should the backup go?")
```

`types` accepts extensions (`"pdf"`, `".png"`) and type identifiers
(`"public.image"` for any image), and `folder` is where the picker opens. {func}`~macos.dialog.choose_file` and
{func}`~macos.dialog.choose_folder` return a {class}`pathlib.Path`, or `None`
if cancelled; {func}`~macos.dialog.choose_files` returns a list, empty if
cancelled.

## Timeouts

{func}`~macos.dialog.alert`, {func}`~macos.dialog.confirm` and
{func}`~macos.dialog.prompt` accept a `timeout` in seconds. When it runs out,
the dialog closes as if the user had cancelled. macOS counts whole seconds, so
a fraction is rounded up (`timeout=1.5` waits 2 seconds):

```python
if macos.dialog.confirm("Restart now?", timeout=30):   # False after 30 s
    restart()
```

## Reference

- {func}`macos.dialog.alert`
- {func}`macos.dialog.confirm`
- {func}`macos.dialog.prompt`
- {func}`macos.dialog.choose`
- {func}`macos.dialog.choose_file`
- {func}`macos.dialog.choose_files`
- {func}`macos.dialog.choose_folder`
