from __future__ import annotations

from pathlib import Path
import novacore


PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "novacore"
if Path(novacore.__file__).resolve() != PACKAGE_ROOT / "__init__.py":
    raise RuntimeError("tests must import NovaCore from this checkout")
