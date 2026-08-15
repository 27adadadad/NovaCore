from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "novacore",
    PACKAGE_ROOT / "__init__.py",
    submodule_search_locations=[str(PACKAGE_ROOT)],
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load NovaCore package from the worktree")

MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["novacore"] = MODULE
SPEC.loader.exec_module(MODULE)
