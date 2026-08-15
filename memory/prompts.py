from __future__ import annotations


MEMORY_EXTRACTION_PROMPT = """Extract only stable, useful long-term memories.

Return a JSON array. Every item must contain scope (user or project), category
(preference, feedback, constraint, or reference), kebab-case title, and content.
Never include credentials, tokens, passwords, complete source code, temporary
debug output, or one-off task progress. Return [] when nothing should be saved.
"""
