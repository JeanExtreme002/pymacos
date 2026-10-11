# -*- coding: utf-8 -*-

"""docs/api.md lists every public name: it's written by hand, so a new function is easy to leave out."""

import importlib
import re
from pathlib import Path

import pytest

import macos

API = Path(__file__).resolve().parents[2] / "docs" / "api.md"


@pytest.mark.skipif(not API.exists(), reason="the docs aren't in this checkout (an installed package)")
def test_api_page_lists_every_public_name():
    documented = set(re.findall(r"^\.\. auto\w+:: (macos\.[\w.]+)", API.read_text(encoding="utf-8"), re.MULTILINE))
    missing = []
    for name in sorted(macos._SUBMODULES):
        module = importlib.import_module("macos." + name)
        for public in module.__all__:
            value = getattr(module, public)
            accepted = {"macos.{}.{}".format(name, public)}
            if macos._SHORTCUTS.get(public) == name:  # documented once, as the top-level shortcut
                accepted.add("macos." + public)
            home = getattr(value, "__module__", None)
            if home and home != module.__name__:  # a re-export: documented where it's defined
                accepted.add("{}.{}".format(home, public))
                accepted.add("macos." + public)
            if not accepted & documented:
                missing.append("macos.{}.{}".format(name, public))
    for shortcut in macos._SHORTCUTS:
        if "macos." + shortcut not in documented:
            missing.append("macos." + shortcut)
    assert not missing, "not in docs/api.md: {}".format(", ".join(missing))
