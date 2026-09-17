"""The two workarounds around pysbd are small functions with their own contract."""

from retake.domain.segmentation import (
    _ascii_quotes,
    _merge_dangling_fragments,
    _merge_split_abbreviations,
    _reattach_leading_closing_quotes,
)


def test_ascii_quotes_maps_typographic_quotes_and_keeps_length() -> None:
    original = "„Komm rein“, sagte er. ‚Wirklich?‘ fragte sie. “Fine,” don’t."

    mapped = _ascii_quotes(original)

    assert mapped == '"Komm rein", sagte er. "Wirklich?" fragte sie. "Fine," don\'t.'
    assert len(mapped) == len(original)  # offsets must stay valid for the original


def test_ascii_quotes_leaves_ascii_text_untouched() -> None:
    assert _ascii_quotes('He said "hi" and didn\'t stop.') == 'He said "hi" and didn\'t stop.'


def test_merge_joins_single_letter_abbreviation_before_number() -> None:
    assert _merge_split_abbreviations(["He was born c.", "1854 in Yorkshire."]) == [
        "He was born c. 1854 in Yorkshire."
    ]


def test_merge_does_not_join_ordinary_sentences() -> None:
    assert _merge_split_abbreviations(["He left.", "1854 was long ago."]) == [
        "He left.",
        "1854 was long ago.",
    ]


def test_merge_does_not_join_when_next_sentence_starts_with_a_letter() -> None:
    assert _merge_split_abbreviations(["Plan c.", "Then go."]) == ["Plan c.", "Then go."]


def test_merge_handles_empty_and_single_lists() -> None:
    assert _merge_split_abbreviations([]) == []
    assert _merge_split_abbreviations(["Only one."]) == ["Only one."]


def test_dangling_closing_quote_joins_previous_sentence() -> None:
    assert _merge_dangling_fragments(["He said it.", "\u201d", "Then left."]) == [
        "He said it.\u201d",
        "Then left.",
    ]


def test_dangling_fragment_at_start_joins_next_sentence() -> None:
    assert _merge_dangling_fragments(["\u201c", "Go home."]) == ["\u201cGo home."]


def test_fragments_only_are_kept_as_one_segment() -> None:
    assert _merge_dangling_fragments(["...", "!"]) == ["...!"]


def test_no_fragments_means_no_change() -> None:
    assert _merge_dangling_fragments(["One.", "Two."]) == ["One.", "Two."]


def test_leading_closing_quote_moves_to_previous_sentence() -> None:
    assert _reattach_leading_closing_quotes(["It was received.", "\u2019 A Frenchman wrote."]) == [
        "It was received.\u2019",
        "A Frenchman wrote.",
    ]


def test_leading_apostrophe_word_is_not_a_closing_quote() -> None:
    assert _reattach_leading_closing_quotes(["He sang.", "'Tis the season."]) == [
        "He sang.",
        "'Tis the season.",
    ]


def test_leading_quote_on_first_sentence_stays() -> None:
    assert _reattach_leading_closing_quotes(["\u201d Odd start."]) == ["\u201d Odd start."]


def test_sentence_that_is_only_a_leading_quote_disappears_into_previous() -> None:
    assert _reattach_leading_closing_quotes(["Done.", "\u201d"]) == ["Done.\u201d"]
