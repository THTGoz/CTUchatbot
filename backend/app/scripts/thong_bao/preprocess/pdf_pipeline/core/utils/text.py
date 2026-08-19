from __future__ import annotations

"""Text helpers whose behavior is identical across pipeline stages.

Only genuinely stage-independent transformations belong here. Stage-specific
functions such as ``normalize_line``, ``normalize_space``, ``normalize_text``,
``clean_text`` and ``normalize_cell`` intentionally remain in their original
scripts until a later commit verifies exact behavioral equivalence.
"""

import unicodedata


def normalize_unicode(text: str) -> str:
    """Apply the Unicode cleanup shared by pipeline steps 02 through 06.

    This function intentionally performs no whitespace collapsing, line joining,
    punctuation repair, PDF-symbol replacement or case conversion.
    """
    return (
        unicodedata.normalize("NFKC", text)
        .replace("\u00a0", " ")
        .replace("\u2007", " ")
        .replace("\u202f", " ")
        .replace("\ufeff", "")
    )
