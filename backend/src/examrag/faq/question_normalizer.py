"""Normalize an extracted question into the form that gets embedded and shown.

Two papers rarely render the same question identically: mark allocations
differ ("[10]" vs "[10 marks]"), quotes come out curly or straight, and
`_STRUCTURAL_LINE` reflow leaves double spaces where a line broke. None of that
is part of the question, and left in, it adds noise the embedding model has no
reason to ignore — a mark allocation is exactly the kind of local detail a
similarity model can latch onto over the actual meaning.
"""

import re
import unicodedata

#: A trailing mark or point allocation: "[10 marks]", "(5 points)", "10%.".
_TRAILING_MARKS = re.compile(
    r"[\[(]?\s*\d{1,3}\s*(marks?|points?|pts?|%)\s*[\])]?\s*\.?\s*$",
    re.IGNORECASE,
)

#: Curly quotes and dashes folded to their plain equivalents, so two renderings
#: of the same question do not differ only in typography. The ambiguous
#: characters are the point, hence the suppressed warning — same as the bullet
#: glyphs `pdf_to_markdown` matches.
_CHARACTER_FOLDS = {
    "‘": "'",  # noqa: RUF001
    "’": "'",  # noqa: RUF001
    "“": '"',
    "”": '"',
    "–": "-",  # noqa: RUF001
    "—": "-",
}


def normalize_question(text: str) -> str:
    """Return the canonical form of an extracted question's text."""
    normalized = unicodedata.normalize("NFKC", text)
    for source, target in _CHARACTER_FOLDS.items():
        normalized = normalized.replace(source, target)

    normalized = _TRAILING_MARKS.sub("", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.rstrip(" ,;:-").strip()
