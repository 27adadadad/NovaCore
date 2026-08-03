from __future__ import annotations

from pathlib import Path

class PathSandbox:
    def __init__(self, project_root:str|Path)->None:
        self._project_root=(
            Path(project_root)
            .expanduser()
            .resolve()
        )

    @property
    def project_root(self)->Path:
        return self._project_root


    def check(self, path:str)->tuple[bool, str]:
        candidate = Path(path).expanduser()

        if not candidate.is_absolute():
            candidate = self._project_root / candidate

        try:
            resolved = candidate.resolve()
        except (
            OSError,
            RuntimeError,
        ) as exc:
            return (
                False,
                "Could not resolve path "
                f"{path}: {exc}",
            )

        try:
            resolved.relative_to(self._project_root)
        except ValueError:
            return False, f"Path outside project root: {path}"
        
        return True, ""
