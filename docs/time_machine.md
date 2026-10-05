# Time Machine

{mod}`macos.time_machine` starts Time Machine backups, follows them, and
chooses what they leave out.

```python
import macos

macos.time_machine.destinations()   # ['Backup Disk']
macos.time_machine.backup_now()
macos.time_machine.is_backing_up()  # True
macos.time_machine.progress()       # 0.42
macos.time_machine.last_backup()    # datetime.datetime(2026, 9, 28, 23, 10, 4)

macos.time_machine.exclude("~/code/app/node_modules")
```

It uses the `tmutil` command that ships with macOS.

## Backing up

{func}`~macos.time_machine.backup_now` starts a backup, like *Back Up Now* in
the Time Machine menu, and returns at once; `wait=True` returns when it's done.
It raises {class}`~macos.MacOSError` when no backup disk is set up.
{func}`~macos.time_machine.stop_backup` stops the one in progress.

```python
macos.time_machine.backup_now(wait=True)
macos.notify("Backup done")
```

## Following a backup

{func}`~macos.time_machine.is_backing_up` tells whether a backup is running, and
{func}`~macos.time_machine.progress` how far it is, from 0.0 to 1.0 (`None` when
none runs, or while it's getting ready).
{func}`~macos.time_machine.last_backup` returns when the latest backup was made,
or `None` when there's none yet or the backup disk isn't connected. It may need
Full Disk Access for the app running Python: without it,
{class}`~macos.PermissionDeniedError` is raised, rather than `None` passing
for "no backup".

## Leaving files out

{func}`~macos.time_machine.exclude` leaves a file or folder out of the backups,
from the next one on: what can be downloaded or rebuilt again
(`node_modules`, virtual environments, caches, virtual machines) only makes
backups big and slow. {func}`~macos.time_machine.include` backs it up again,
but doesn't undo an exclusion made in System Settings or by macOS itself.

```python
from pathlib import Path

for folder in Path("~/code").expanduser().glob("*/node_modules"):
    macos.time_machine.exclude(folder)
```

The choice travels with the file: it stays when the file is moved or renamed.
It needs no administrator password, but doesn't show in System Settings'
*Exclude from Backups* list either. Copies made before stay on the backup disk.

{func}`~macos.time_machine.is_excluded` tells whether Time Machine leaves a path
out for any reason: {func}`~macos.time_machine.exclude`, the list in System
Settings, or macOS itself, which skips caches and temporary files. What's
inside an excluded folder is excluded too.

## Reference

- {func}`macos.time_machine.destinations`
- {func}`macos.time_machine.backup_now`
- {func}`macos.time_machine.stop_backup`
- {func}`macos.time_machine.is_backing_up`
- {func}`macos.time_machine.progress`
- {func}`macos.time_machine.last_backup`
- {func}`macos.time_machine.exclude`
- {func}`macos.time_machine.include`
- {func}`macos.time_machine.is_excluded`
