# Contributing

Bug reports, ideas and pull requests are welcome on
[GitHub](https://github.com/JeanExtreme002/pymacos).

## Setup

```bash
git clone https://github.com/JeanExtreme002/pymacos.git
cd pymacos
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

The `Makefile` wraps every command below: run `make help` to list the targets,
for example `make check` (lint, type check and unit tests) or `make docs`.

## Tests

```bash
make test               # unit and live tests, but not the intrusive ones (below), even with a switch set
make test-all           # every test, the intrusive ones included: run it at the Mac
make test-unit          # unit tests only (these also run on Linux): pytest tests/unit
make test-live          # live tests only, not the intrusive ones; make test-live-all: with them
pytest                  # unit and live tests, the intrusive ones only when their switch is on
pytest tests/unit/test_audio.py tests/live/test_audio.py   # one module
```

The tests are in two folders, with one file per module (`test_audio.py`
tests `macos.audio`):

- `tests/unit`: fake the system commands and frameworks, and run anywhere.
- `tests/live`: talk to the real system, and are skipped outside macOS.

Helpers shared by several files are in `tests/helpers.py`, and each folder's
fixtures in its `conftest.py`.

The live tests talk to the real system, so run them when you aren't typing
elsewhere. Without any switch they: use and restore the clipboard, mute and
unmute the volume, show three dialogs for a second each, open a small test
window and give the focus back, create and delete a Keychain item, a Time
Machine exclusion and a disk image, and ask once for the Automation permission
(System Events). The more intrusive ones only run when asked, with an
environment variable; `make test-all` and `make test-live-all` set them all:

| Variable | Unlocks |
|---|---|
| `PYMACOS_CAPTURE_TESTS=1` | the camera and the microphone |
| `PYMACOS_BROWSER_TESTS=1` | reading your browser's tabs (macOS asks permission) |
| `PYMACOS_SCHEDULE_TESTS=1` | adding, then removing, a launch agent (macOS announces it) |
| `PYMACOS_SETTINGS_TESTS=1` | changing, then restoring, settings: the Dock, login items, a default app, the display mode, a keyboard remap |

Every switch, these and `PYMACOS_REQUIRE_PERMISSIONS` below, is on when set
to `1`, `true`, `yes` or `on`, in any case; `0`, `false`, `no`, `off` or
leaving it unset keeps it off (anything else is off too, with a warning).
On GitHub's runners (`GITHUB_ACTIONS=true`) the schedule and settings tests
run unasked: the machine is thrown away afterwards. A self-hosted runner on
your own Mac sets `GITHUB_ACTIONS=true` too, so it unlocks them as well.
`CI` alone unlocks nothing.
The tests that need a permission the machine lacks (Accessibility, Screen
Recording, Input Monitoring) skip themselves: `pytest -rs` lists them, so you
can tell a green run with gaps from a full one.
`PYMACOS_REQUIRE_PERMISSIONS=1` turns those skips into failures: CI sets it on
the runners that have the permissions, so losing them can't go unnoticed.

## Lint and type check

```bash
flake8 macos tests
mypy macos
```

## Documentation

```bash
pip install -r docs/requirements.txt
python -m sphinx -n -W --keep-going -b html docs docs/_build/html
```

Then open `docs/_build/html/index.html`.

## Pull requests

- Use [Conventional Commits](https://www.conventionalcommits.org) for the title
  (`feat: ...`, `fix: ...`, `docs: ...`). The type is one of `feat`, `fix`,
  `perf`, `refactor`, `revert`, `docs`, `ci`, `build`, `chore`, `test` or
  `style`, and the subject starts with a lowercase letter and doesn't end with
  a period. A check enforces it.
- Add a test for every bug fix and new feature.
- Keep the package dependency-free.

## Compatibility

pymacos follows [Semantic Versioning](https://semver.org): a minor release
never breaks code that works with the previous one.

- To rename or remove a public function, keep the old one for at least one
  minor release, decorated with `macos._system.deprecated`, which warns
  (`DeprecationWarning`) and says what to use instead. It's removed only in
  the next major release.
- New arguments are keyword-only and have a default, so existing calls keep
  their meaning.
- Changing what a function returns or raises counts as breaking, unless the
  old behaviour contradicted its documentation (that's a bug fix). That
  includes raising where it used to return (`False`, `None`, `[]`), raising
  an exception the old one's `except` clauses don't catch (a subclass of it
  is fine), and refusing a call it used to accept (another thread, an
  argument it took). Such a change waits for the next major release; until
  then, keep the old behaviour where you can and warn (`DeprecationWarning`)
  that it will change, saying what to do instead.
- A release's notes list every such change, under *Changed*.

## Releases

The release notes on [GitHub Releases](https://github.com/JeanExtreme002/pymacos/releases)
are the changelog: there's no `CHANGELOG.md` to keep in step with them.

1. Merge the changes the release ships.
2. Open a pull request titled `chore: bump version to X.Y.Z` that only
   changes `__version__` in `macos/__init__.py`, following the rules above
   (a patch for fixes, a minor release for anything new), and merge it.
3. On GitHub, create a release whose tag is `vX.Y.Z`, made from `main`. The
   notes open with `pip install --upgrade pymacos` and a sentence on what the
   release is, then list the changes under *New*, *Changed* (worth a look if
   you rely on them) and *Fixed*, and end with a link to the docs.

Publishing the release starts the `Publish to PyPI` workflow: it refuses a
tag that doesn't match `__version__` or isn't on `main`, builds the package
once, runs the whole suite (live tests included) against that build, and only
then uploads it.
