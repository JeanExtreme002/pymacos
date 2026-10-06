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
for example `make check` (lint, type check and tests) or `make docs`.

## Tests

```bash
pytest                  # everything, including live tests on your Mac
pytest tests/unit       # unit tests only (these also run on Linux)
pytest tests/unit/test_audio.py tests/live/test_audio.py   # one module
```

The tests are in two folders, with one file per module (`test_audio.py`
tests `macos.audio`):

- `tests/unit`: fake the system commands and frameworks, and run anywhere.
- `tests/live`: talk to the real system, and are skipped outside macOS.

Helpers shared by several files are in `tests/helpers.py`, and each folder's
fixtures in its `conftest.py`.

The live tests talk to the real system. They restore your clipboard and delete
the Keychain items they create. The ones that turn the camera or the microphone
on only run when asked: `PYMACOS_CAPTURE_TESTS=1 pytest`. So do the ones that read
your browser's tabs (`PYMACOS_BROWSER_TESTS=1`) and, outside CI, the one that adds
a launch agent (`PYMACOS_SCHEDULE_TESTS=1`) or change, then restore, a setting of
the Mac: the Dock, login items, a default app (`PYMACOS_SETTINGS_TESTS=1`).

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
  old behaviour contradicted its documentation (that's a bug fix).
