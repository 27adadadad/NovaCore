from __future__ import annotations

import re

_DEFAULT_PATTERNS:list[tuple[str, str]] = [
    (
        r"\b(?:format|format\.com)\s+[a-z]:",
        "Formatting a disk drive",
    ),
    (
        r"\brm\s+-(?=[a-z]*r)(?=[a-z]*f)[a-z]+\s+/\s*$",
        "Recursive forced deletion of root directory",
    ),
    (
        r"\b(?:curl|wget)\b.*\|\s*(?:ba)?sh\b",
        "Downloading and executing a remote script",
    ),
    (
        r"\bremove-item\b(?=.*-recurse).*?[a-z]:\\[\"']?\s*$",
        "Recursive deletion of a drive root",
    ),       
]
class DangerousCommandDetector:
    def __init__(
        self,
        extra_patterns:list[tuple[str, str]] | None = None,
    )->None:
        patterns = list(_DEFAULT_PATTERNS)

        if extra_patterns:
            patterns.extend(extra_patterns)

        self._patterns = [
            (
                re.compile(pattern, re.IGNORECASE),
                reason,
            )
            for pattern, reason in patterns
        ]

    def detect(
        self,
        command:str,
    )->tuple[bool, str]:
        for pattern ,reason in self._patterns:
            if pattern.search(command):
                return True, reason
            
        return False, ""