# Installation

Install from PyPI:

```bash
pip install pymacos
```

The distribution is named `pymacos` on PyPI, but the package you import is
`macos`:

```python
import macos
```

The library has no dependencies and needs no compiler: it's pure Python.

## Requirements

- macOS (some features need macOS 12, 14 or 15; their pages say which)
- Python 3.9 or later

Every change is tested on the current macOS, on Apple silicon, and on the
previous one, on both Apple silicon and Intel.

## Other operating systems

The package *imports* on any OS, so it's safe to use in cross-platform code and
to build docs on Linux. Calling one of its functions outside macOS raises
{class}`~macos.NotSupportedError`:

```python
import sys
import macos

if sys.platform == "darwin":
    macos.notify("Hello from a Mac")
```
