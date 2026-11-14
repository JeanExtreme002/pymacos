"""
Not the package: ``pymacos`` is the name on PyPI, and the module it installs is :mod:`macos`.

This one is here for whoever writes ``import pymacos`` after ``pip install pymacos``: without it, that's a
``ModuleNotFoundError`` that reads as a broken install. It isn't an alias on purpose: the library has one name.
"""

raise ImportError("pymacos is the name on PyPI, the module is called macos: write 'import macos' instead of 'import pymacos'")
