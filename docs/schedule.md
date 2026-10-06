# Schedule

{mod}`macos.schedule` runs your Python scripts on a schedule, when you log in,
when a folder changes or when a disk is plugged in, with launchd: the Mac's
cron, without writing its XML by hand.

```python
import macos

macos.schedule.add("backup", "~/scripts/backup.py", every=3600)       # every hour
macos.schedule.add("report", "report.py", at="09:00")                 # every day at 9
macos.schedule.add("sync", "sync.py", at="18:30", weekdays=["mon", "fri"])
macos.schedule.add("hello", "hello.py", at_login=True)
macos.schedule.add("tidy", "tidy.py", when_changed="~/Downloads")     # a file arrives
macos.schedule.add("copy", "copy.py", at_mount=True)                  # a disk is plugged in
```

A job keeps running after your script ends and after a restart, as long as
you're logged in. When the Mac was asleep at the scheduled time, the job runs
when it wakes up.

## Adding a job

{func}`~macos.schedule.add` takes a name (letters, digits, `.`, `_`, `-`),
the script, and when to run it:

- `every`: seconds between runs, or a {class}`~datetime.timedelta`.
- `at`: a time of day, `"09:00"` or a {class}`~datetime.time`, or a list of
  them; with `weekdays` (`["mon", "wed", "fri"]`), only on those days.
  `every` and `at` can't go together, and `weekdays` needs `at`.
- `at_login=True`: each time you log in, and once right away.
- `when_changed`: a file or folder, or a list of them: see
  [Running when something happens](#running-when-something-happens).
- `at_mount=True`: each time a disk is mounted.

```python
macos.schedule.add("tidy", "tidy_downloads.py", at=["08:00", "20:00"])
macos.schedule.add("scrape", "scrape.py", every=900, args=["--quiet"], python="~/venvs/scrape/bin/python")
```

The script runs with the same Python that added it (or `python=`, such as a
virtual environment's), in its own folder, with `args` as its arguments.
Adding a name again replaces that job. If launchd refuses the new one, `add`
deletes its plist, puts the old job back (still paused if it was) and raises
the error.

macOS announces the new job with a *Background Items Added* notification,
and lists it in System Settings › General › Login Items & Extensions. The
script runs outside your terminal, so it doesn't get the terminal's
[permissions](permissions.md): macOS asks for them again, for Python.

## Running when something happens

`when_changed` runs the script when a file changes, or when a file is added to,
removed from or renamed in a folder (not in its subfolders). It keeps working
after a restart, with no Python left running: launchd watches for it.

```python
macos.schedule.add("tidy", "~/scripts/tidy_downloads.py", when_changed="~/Downloads")
```

```python
# tidy_downloads.py: move the PDFs into their own folder.
from pathlib import Path

downloads = Path("~/Downloads").expanduser()
pdfs = downloads / "PDFs"
pdfs.mkdir(exist_ok=True)
for file in downloads.glob("*.pdf"):
    file.rename(pdfs / file.name)
```

The script isn't told what changed: it looks at the folder itself. Changes
made while it runs, or a few seconds apart, lead to one more run, not one
each, and moving files out of the folder counts as a change too, so the script
should do nothing when there's nothing left to do. A path that doesn't exist
yet counts once it's created. launchd may also run the script once as the job
is added.

`at_mount=True` runs it each time a disk is mounted: an external drive, a USB
stick, a disk image, a network share. The script can look at `/Volumes` to
find which:

```python
macos.schedule.add("backup-photos", "copy_photos.py", at_mount=True)
```

These combine with `every`, `at` and `at_login`:
`every=3600, when_changed="~/Inbox"` runs hourly and on changes.

## Checking on jobs

```python
for job in macos.schedule.jobs():
    print(job.name, job.every or job.at, job.last_exit_status)

job = macos.schedule.get("backup")
print(job.log.read_text())         # what the script printed, and its errors

macos.schedule.run_now("backup")   # run it once now, besides its schedule
macos.schedule.pause("backup")     # off its schedule, until resume("backup")
macos.schedule.remove("backup")
```

Each {class}`~macos.schedule.Job` tells whether it's `running`, and how the
last run ended (`last_exit_status`, 0 for success). The script's output and
errors go to `job.log`, in `~/Library/Logs/pymacos`.
{func}`~macos.schedule.pause` keeps a job without running it, even after a
restart, and `job.paused` tells; {func}`~macos.schedule.resume` puts it back on
its schedule. Pausing or removing a job also stops a run in progress.

## Reference

- {func}`macos.schedule.add`
- {func}`macos.schedule.remove`
- {func}`macos.schedule.jobs`
- {func}`macos.schedule.get`
- {func}`macos.schedule.run_now`
- {func}`macos.schedule.pause`
- {func}`macos.schedule.resume`
- {class}`macos.schedule.Job`
