"""Unit tests for :mod:`macos.printer`, against a fake CUPS. They run on any platform."""

import ctypes
from pathlib import Path

import pytest

import macos
from macos import printer


class FakeCups:
    """The few libcups functions the module calls, over Python lists."""

    def __init__(self):
        self.printers = [
            ("Office_LaserJet", {"printer-info": "Office LaserJet", "printer-state": "3", "printer-make-and-model": "HP"}, True),
            ("Home", {"printer-info": "Home Inkjet"}, False),
        ]
        self.jobs = []
        self.printed = []
        self.canceled = []
        self._keep = []  # the ctypes arrays handed out, kept alive while in use

    def cupsGetDests(self, pointer):
        if not self.printers:
            return 0
        array = (printer._Dest * len(self.printers))()
        for index, (name, options, is_default) in enumerate(self.printers):
            pairs = (printer._Option * len(options))(*[printer._Option(k.encode(), v.encode()) for k, v in options.items()])
            self._keep.append(pairs)
            array[index] = printer._Dest(name.encode(), None, int(is_default), len(options), pairs)
        self._keep.append(array)
        pointer._obj.contents = array[0]
        return len(self.printers)

    def cupsFreeDests(self, count, dests):
        pass

    def cupsAddOption(self, name, value, count, pointer):
        self.options = getattr(self, "options", {}) if count else {}
        self.options[name.decode()] = value.decode()
        return count + 1

    def cupsFreeOptions(self, count, options):
        pass

    def cupsPrintFile(self, name, filename, title, count, options):
        job_id = len(self.jobs) + 1
        self.printed.append((name.decode(), Path(filename.decode()).name, title.decode(), dict(self.options)))
        self.jobs.append((job_id, name.decode(), title.decode(), 5))
        return job_id

    def cupsGetJobs(self, pointer, name, mine, which):
        wanted = [job for job in self.jobs if name is None or job[1] == name.decode()]
        if which == 0:
            wanted = [job for job in wanted if job[3] <= 6]
        if not wanted:
            return 0
        array = (printer._Job * len(wanted))()
        for index, (job_id, dest, title, state) in enumerate(wanted):
            array[index] = printer._Job(job_id, dest.encode(), title.encode(), b"alice", b"", state, 12, 50, 0, 1700000000, 0)
        self._keep.append(array)
        pointer._obj.contents = array[0]
        return len(wanted)

    def cupsFreeJobs(self, count, jobs):
        pass

    def cupsCancelJob(self, name, job_id):
        self.canceled.append((name.decode() if name else None, job_id))
        self.jobs = [(i, d, t, 7 if i == job_id else s) for i, d, t, s in self.jobs]
        return 1

    def cupsLastErrorString(self):
        return b"The printer is gone"


@pytest.fixture
def cups(monkeypatch):
    fake = FakeCups()
    monkeypatch.setattr(printer, "_cups", lambda: fake)
    return fake


def test_printers_and_default(cups):
    found = printer.printers()
    assert [p.name for p in found] == ["Office_LaserJet", "Home"]
    assert found[0] == printer.Printer("Office_LaserJet", "Office LaserJet", "HP", None, True, "idle")
    assert found[1].state is None and found[1].description == "Home Inkjet"
    assert printer.default().name == "Office_LaserJet"
    cups.printers = [(name, options, False) for name, options, _ in cups.printers]
    assert printer.default() is None


def test_print_file_jobs_and_cancel(cups, tmp_path):
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF")

    job = printer.print_file(
        report, "Home Inkjet", copies=2, pages="1-3, 7", two_sided=True, black_and_white=True, paper="A4"
    )
    assert cups.printed == [
        (
            "Home",
            "report.pdf",
            "report.pdf",
            {
                "copies": "2",
                "page-ranges": "1-3,7",
                "sides": "two-sided-long-edge",
                "print-color-mode": "monochrome",
                "media": "A4",
            },
        )
    ]
    assert (job.id, job.printer, job.state, job.user, job.size) == (1, "Home", "processing", "alice", 12)
    printer.print_file(report, title="Monthly report")  # the default printer
    assert cups.printed[-1][0] == "Office_LaserJet" and cups.printed[-1][2] == "Monthly report"
    assert [j.id for j in printer.jobs()] == [1, 2] and [j.id for j in printer.jobs("Home")] == [1]
    job.cancel()
    assert cups.canceled == [("Home", 1)]
    assert [j.id for j in printer.jobs()] == [2]
    assert [(j.id, j.state) for j in printer.jobs(finished=True)] == [(1, "canceled"), (2, "processing")]
    printer.cancel(2)
    assert cups.canceled[-1] == (None, 2)


def test_print_file_checks(cups, tmp_path, monkeypatch):
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF")
    with pytest.raises(FileNotFoundError):
        printer.print_file(tmp_path / "missing.pdf")
    with pytest.raises(ValueError, match="copies"):
        printer.print_file(report, copies=0)
    with pytest.raises(ValueError, match="no printer is named 'Garage'"):
        printer.print_file(report, "Garage")
    monkeypatch.setattr(cups, "cupsPrintFile", lambda *args: 0)
    with pytest.raises(macos.MacOSError, match="The printer is gone"):
        printer.print_file(report)
    cups.printers = []
    with pytest.raises(macos.MacOSError, match="no default printer"):
        printer.print_file(report)


def test_set_default(cups, fake_run):
    printer.set_default("Home Inkjet")
    assert fake_run.args == ["lpoptions", "-d", "Home"] and fake_run.calls[-1]["timeout"]


def test_structs_match_libcups():
    # cups_dest_t and cups_job_t, as in <cups/cups.h>.
    pointer = ctypes.sizeof(ctypes.c_void_p)
    assert ctypes.sizeof(printer._Dest) == 2 * pointer + 2 * 4 + pointer
    assert printer._Job.state.offset == 4 * pointer + pointer  # after id (padded) and four strings


def test_printers_named_by_queue_first_and_ambiguous_descriptions_refused(cups, tmp_path):
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF")
    cups.printers = [
        ("Office_1", {"printer-info": "Office"}, True),
        ("Office_2", {"printer-info": "Office"}, False),
        ("Office", {"printer-info": "Front desk"}, False),
    ]
    printer.print_file(report, "Office")  # the queue's name wins over two descriptions
    assert cups.printed[-1][0] == "Office"
    cups.printers = cups.printers[:2]
    with pytest.raises(ValueError, match="several printers are named 'Office': use one of their queue names, Office_1, Office_2"):
        printer.print_file(report, "Office")
