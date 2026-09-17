"""Split a chapter into sentence segments with stable positions and paragraph indices (R2, R3).

Sentence boundaries come from pysbd (ADR-0004), wrapped so nothing outside this module
touches the library. Small, tested helpers cover what pysbd 0.3.4 gets wrong for us:
`_ascii_quotes` (typographic quotes), `_reattach_leading_closing_quotes` and
`_merge_dangling_fragments` (closing quotes pushed into the wrong sentence) and
`_merge_split_abbreviations` (`c. 1854`). Comment lines (`//`) are removed before splitting.
"""

import re
import warnings
from dataclasses import dataclass

# pysbd 0.3.4 (2021) uses non-raw regex strings that Python 3.12 flags at compile time.
# Silence only that library, only that warning.
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=SyntaxWarning, module=r"pysbd(\..*)?")
    import pysbd

COMMENT_PREFIX = "//"

_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")
_WHITESPACE_RUN = re.compile(r"\s+")
_ENDS_WITH_SINGLE_LETTER_ABBREVIATION = re.compile(r"(?:^|\s)[a-z]\.$")
_HAS_WORD_CHARACTER = re.compile(r"\w")
# A sentence never starts with a closing quote followed by a space; pysbd sometimes
# pushes the closing quote of the previous sentence there.
_LEADING_CLOSING_QUOTES = re.compile("^[\u2019\u201d'\"]+(?=\\s|$)")

# Length-preserving map so that offsets from the normalised copy apply to the original text.
# Keys are code points (the characters themselves would trip ruff's ambiguous-unicode check).
_QUOTE_MAP = str.maketrans(
    {
        0x201E: '"',  # DOUBLE LOW-9 QUOTATION MARK (German opening double)
        0x201C: '"',  # LEFT DOUBLE QUOTATION MARK
        0x201D: '"',  # RIGHT DOUBLE QUOTATION MARK
        0x201A: '"',  # SINGLE LOW-9 QUOTATION MARK (German opening single)
        0x2018: '"',  # LEFT SINGLE QUOTATION MARK (English opening / German closing single)
        0x2019: "'",  # RIGHT SINGLE QUOTATION MARK (English closing single, apostrophe)
    }
)
# Opening single quotes become double quotes because pysbd only recognises ASCII double
# quotes around speech; the closing/apostrophe form stays a single quote so pysbd does not
# treat "don't" as a quote. The resulting imbalance can leave a lone closing quote as its own
# "sentence", which _merge_dangling_fragments repairs.

_segmenter = pysbd.Segmenter(language="en", clean=False, char_span=True)


@dataclass(frozen=True, slots=True)
class SegmentDraft:
    """A sentence to be generated. `position` is gapless from 0 across the whole chapter."""

    text: str
    position: int
    paragraph_index: int


def split(text: str) -> list[SegmentDraft]:
    """Pure function: chapter text in, sentence drafts out. Never raises on odd input."""
    drafts: list[SegmentDraft] = []
    paragraph_index = 0
    for paragraph in _paragraphs(text):
        sentences = _sentences(paragraph)
        if not sentences:
            continue
        for sentence in sentences:
            drafts.append(
                SegmentDraft(sentence, position=len(drafts), paragraph_index=paragraph_index)
            )
        paragraph_index += 1
    return drafts


def _paragraphs(text: str) -> list[str]:
    """Blank-line separated blocks with comment lines removed and whitespace collapsed."""
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    kept_lines = [line for line in normalised.split("\n") if not _is_comment(line)]
    blocks = _PARAGRAPH_BREAK.split("\n".join(kept_lines))
    return [p for p in (_WHITESPACE_RUN.sub(" ", block).strip() for block in blocks) if p]


def _is_comment(line: str) -> bool:
    return line.lstrip().startswith(COMMENT_PREFIX)


def _sentences(paragraph: str) -> list[str]:
    """Sentence texts of one paragraph, sliced from the original so no character changes."""
    spans = _segmenter.segment(_ascii_quotes(paragraph))
    raw = [paragraph[span.start : span.end].strip() for span in spans]
    sentences = [s for s in raw if s]
    sentences = _reattach_leading_closing_quotes(sentences)
    sentences = _merge_dangling_fragments(sentences)
    return _merge_split_abbreviations(sentences)


def _ascii_quotes(text: str) -> str:
    """Map typographic quotes to ASCII ones, keeping every character position.

    pysbd only understands ASCII quotes around speech; the result is used for finding
    boundaries only, never returned to the caller.
    """
    return text.translate(_QUOTE_MAP)


def _reattach_leading_closing_quotes(sentences: list[str]) -> list[str]:
    """Move closing quotes that pysbd left at the start of a sentence back to the previous one.

    `received.\u2019 A Frenchman` is cut as `received.` | `\u2019 A Frenchman`; the quote belongs
    to the first part. Only a quote run followed by whitespace qualifies, so `'Tis` is untouched.
    """
    fixed: list[str] = []
    for sentence in sentences:
        match = _LEADING_CLOSING_QUOTES.match(sentence)
        if match and fixed:
            fixed[-1] = f"{fixed[-1]}{match.group(0)}"
            sentence = sentence[match.end() :].lstrip()
            if not sentence:
                continue
        fixed.append(sentence)
    return fixed


def _merge_dangling_fragments(sentences: list[str]) -> list[str]:
    """Attach a "sentence" without any letter or digit (e.g. a lone closing quote) to its
    neighbour: to the previous sentence, or to the next one if it comes first."""
    merged: list[str] = []
    pending_prefix = ""
    for sentence in sentences:
        if not _HAS_WORD_CHARACTER.search(sentence):
            if merged:
                merged[-1] = f"{merged[-1]}{sentence}"
            else:
                pending_prefix += sentence
            continue
        merged.append(f"{pending_prefix}{sentence}")
        pending_prefix = ""
    if pending_prefix and merged:
        merged[-1] = f"{merged[-1]}{pending_prefix}"
    elif pending_prefix:
        merged.append(pending_prefix)
    return merged


def _merge_split_abbreviations(sentences: list[str]) -> list[str]:
    """Re-join a sentence pysbd cut after a single-letter abbreviation before a number.

    `c. 1854` (circa) is split by pysbd into `... c.` and `1854 ...`; a sentence never ends
    with a lone lowercase letter followed by a number, so merging is safe.
    """
    merged: list[str] = []
    for sentence in sentences:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and _ENDS_WITH_SINGLE_LETTER_ABBREVIATION.search(previous)
            and sentence[:1].isdigit()
        ):
            merged[-1] = f"{previous} {sentence}"
        else:
            merged.append(sentence)
    return merged
