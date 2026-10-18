# Printer

{mod}`macos.printer` lists the printers, prints files and follows the print
queue, through CUPS, the printing system of macOS.

```python
import macos

[p.description for p in macos.printer.printers()]   # ['Office LaserJet', 'Home Inkjet']

job = macos.printer.print_file("report.pdf", copies=2, two_sided=True)
macos.printer.jobs()   # [PrintJob(id=12, title='report.pdf', state='processing', ...)]
job.cancel()
```

No permission is needed. Printing sends the file straight to the printer,
without a print dialog.

## Printers

{func}`~macos.printer.printers` lists the printers set up in System Settings ›
Printers & Scanners, the default one first. Each
{class}`~macos.printer.Printer` has its queue `name`, the `description`
System Settings shows, its `model`, `location`, whether it `is_default`, and
its `state` (`"idle"`, `"printing"`, `"stopped"`, or `None` when the printer
doesn't say, as network printers often don't). When your default is a saved
set of options for a printer (an `lpoptions` instance such as
`Office/duplex`), that printer is the default; printing without naming one
sends the job to it without the instance's options.

```python
macos.printer.default()                     # Printer(name='Office_LaserJet', ...), or None
macos.printer.set_default("Home Inkjet")    # by its description or its name
```

## Printing

{func}`~macos.printer.print_file` prints a PDF, an image or a text file on the
default printer, or on the one named, and returns the
{class}`~macos.printer.PrintJob`:

```python
macos.printer.print_file("invoice.pdf")
macos.printer.print_file(
    "slides.pdf", "Office LaserJet", pages="1-3,7", copies=2, two_sided=True, black_and_white=True, paper="A4"
)
```

It returns once the file is queued, not printed. `title` names the job in the
queue; it's the file's name by default.

## The queue

{func}`~macos.printer.jobs` lists the jobs waiting or printing, on every
printer or on one; `finished=True` adds those done, canceled or aborted.
{meth}`PrintJob.cancel() <macos.printer.PrintJob.cancel>` or
{func}`~macos.printer.cancel` takes one out. A job's `id` is 1 or more:
`cancel()` refuses 0 and negative numbers with `ValueError`, which CUPS would
read as the job printing now or every job on the printer.

```python
for job in macos.printer.jobs("Office LaserJet"):
    print(job.id, job.title, job.state)   # 12 report.pdf processing
    job.cancel()
```

## Reference

- {func}`macos.printer.printers`
- {func}`macos.printer.default`
- {func}`macos.printer.set_default`
- {func}`macos.printer.print_file`
- {func}`macos.printer.jobs`
- {func}`macos.printer.cancel`
- {class}`macos.printer.Printer`
- {class}`macos.printer.PrintJob`
