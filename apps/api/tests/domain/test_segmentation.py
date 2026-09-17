"""Behaviour of `domain.segmentation.split` (R2, R3).

Pure function: text in, list[SegmentDraft] out. No I/O, no framework imports.
Written before the implementation (TDD); read these expectations first.
"""

import dataclasses

import pytest

from retake.domain.segmentation import SegmentDraft, split


def texts(text: str) -> list[str]:
    return [s.text for s in split(text)]


# ---------------------------------------------------------------- basics


def test_empty_text_gives_empty_list() -> None:
    assert split("") == []


def test_whitespace_only_text_gives_empty_list() -> None:
    assert split("   \n\n \t ") == []


def test_splits_on_period_exclamation_and_question_mark() -> None:
    assert texts("It was late. Nobody came! Why not?") == [
        "It was late.",
        "Nobody came!",
        "Why not?",
    ]


def test_text_without_terminal_punctuation_is_still_a_segment() -> None:
    assert texts("Chapter One") == ["Chapter One"]


def test_positions_are_gapless_from_zero() -> None:
    drafts = split("One. Two. Three.\n\nFour. Five.")

    assert [d.position for d in drafts] == list(range(len(drafts)))
    assert len(drafts) == 5


def test_segment_draft_is_immutable() -> None:
    draft = split("Fixed.")[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.text = "Changed."  # type: ignore[misc]


# ---------------------------------------------------------------- abbreviations


@pytest.mark.parametrize(
    "text",
    [
        "Mr. Holmes sat down.",
        "Dr. Watson followed him.",
        "Mrs. Hudson brought tea.",
        "They walked along St. James Street.",
        "Bring a tool, e.g. a hammer, and wait.",
        "He was born c. 1854 in Yorkshire.",
    ],
)
def test_abbreviations_do_not_split(text: str) -> None:
    assert texts(text) == [text]


def test_abbreviation_followed_by_new_sentence() -> None:
    assert texts("Mr. Holmes sat down. Dr. Watson followed.") == [
        "Mr. Holmes sat down.",
        "Dr. Watson followed.",
    ]


# ---------------------------------------------------------------- quotes


def test_closing_quote_after_period_belongs_to_the_sentence() -> None:
    assert texts('He said, "Go home." Then he left.') == ['He said, "Go home."', "Then he left."]


def test_quoted_speech_with_attribution_is_one_sentence() -> None:
    assert texts('"Come in," said Holmes.') == ['"Come in," said Holmes.']


def test_question_mark_inside_quote_does_not_end_the_sentence() -> None:
    assert texts('"Really?" she asked.') == ['"Really?" she asked.']


def test_two_quoted_sentences() -> None:
    assert texts('"Come in," said Holmes. "Really?" she asked.') == [
        '"Come in," said Holmes.',
        '"Really?" she asked.',
    ]


def test_unicode_double_quotes() -> None:
    assert texts("“Come in,” said Holmes. “Why?” she asked.") == [
        "“Come in,” said Holmes.",
        "“Why?” she asked.",
    ]


def test_unicode_german_quotes() -> None:
    assert texts("„Komm rein“, sagte er. ‚Wirklich?‘ fragte sie.") == [
        "„Komm rein“, sagte er.",
        "‚Wirklich?‘ fragte sie.",
    ]


def test_single_quoted_phrase_inside_double_quoted_speech() -> None:
    # From the fixture: nested quotes must not leave a dangling closing quote segment.
    text = (
        "\u201cNote the sentence\u2014\u2018This we have received.\u2019 "
        "A Frenchman could not have written that.\u201d"
    )

    assert texts(text) == [
        "\u201cNote the sentence\u2014\u2018This we have received.\u2019",
        "A Frenchman could not have written that.\u201d",
    ]


# ---------------------------------------------------------------- ellipses and dashes


def test_ellipsis_followed_by_lowercase_does_not_split() -> None:
    assert texts("I waited... nothing happened.") == ["I waited... nothing happened."]


def test_ellipsis_at_sentence_end_splits_before_capital() -> None:
    assert texts("It was over... She left.") == ["It was over...", "She left."]


def test_unicode_ellipsis_character_is_treated_like_three_dots() -> None:
    assert texts("I waited… nothing happened.") == ["I waited… nothing happened."]


def test_em_and_en_dashes_do_not_split() -> None:
    assert texts("He stopped — then ran. She waited – and left.") == [
        "He stopped — then ran.",
        "She waited – and left.",
    ]


# ---------------------------------------------------------------- numbers


def test_decimal_number_does_not_split() -> None:
    assert texts("It cost 3.5 million dollars.") == ["It cost 3.5 million dollars."]


def test_street_abbreviation_mid_sentence_does_not_split() -> None:
    assert texts("He lived at 221B Baker St. for years.") == [
        "He lived at 221B Baker St. for years."
    ]


# ---------------------------------------------------------------- paragraphs (R3)


def test_blank_line_starts_a_new_paragraph() -> None:
    drafts = split("First one. First two.\n\nSecond one.")

    assert [(d.text, d.paragraph_index) for d in drafts] == [
        ("First one.", 0),
        ("First two.", 0),
        ("Second one.", 1),
    ]


def test_multiple_blank_lines_count_as_one_boundary_and_create_no_empty_segments() -> None:
    drafts = split("One.\n\n\n\n\nTwo.")

    assert [(d.text, d.paragraph_index) for d in drafts] == [("One.", 0), ("Two.", 1)]


def test_whitespace_only_line_is_a_paragraph_boundary() -> None:
    drafts = split("One.\n   \nTwo.")

    assert [d.paragraph_index for d in drafts] == [0, 1]


def test_single_newline_inside_a_paragraph_is_a_space() -> None:
    # Project Gutenberg text is hard-wrapped at ~70 columns; a lone newline is not a boundary.
    drafts = split("The night was\ncold and dark. He\nwaited.")

    assert [(d.text, d.paragraph_index) for d in drafts] == [
        ("The night was cold and dark.", 0),
        ("He waited.", 0),
    ]


def test_windows_line_endings_are_handled() -> None:
    drafts = split("One.\r\n\r\nTwo.")

    assert [(d.text, d.paragraph_index) for d in drafts] == [("One.", 0), ("Two.", 1)]


# ---------------------------------------------------------------- whitespace


def test_surrounding_whitespace_is_stripped() -> None:
    assert texts("   Hello world.  \n") == ["Hello world."]


def test_runs_of_spaces_and_tabs_collapse_to_one_space() -> None:
    # Never content, but billed by TTS and noise in the diff.
    assert texts("Hello \t  world,   again.") == ["Hello world, again."]


def test_whitespace_between_sentences_is_not_part_of_either() -> None:
    assert texts("One.    Two.") == ["One.", "Two."]


# ---------------------------------------------------------------- comment lines
# Convention: a line whose first non-blank characters are `//` is a comment and is removed
# before segmentation (used for the source/licence header in fixtures/chapter-clean.txt).
# `//` rather than `#` because `# Heading` is Markdown, which R1 allows as input.


def test_comment_header_is_skipped() -> None:
    text = "// Source: Project Gutenberg\n// Licence: public domain\n\nIt began."

    assert texts(text) == ["It began."]


def test_comment_line_between_paragraphs_is_not_a_segment_and_not_a_boundary() -> None:
    drafts = split("One.\n// note to self\nTwo.")

    assert [(d.text, d.paragraph_index) for d in drafts] == [("One.", 0), ("Two.", 0)]


def test_indented_comment_line_is_skipped() -> None:
    assert texts("   // indented comment\nReal text.") == ["Real text."]


def test_double_slash_inside_a_sentence_is_not_a_comment() -> None:
    assert texts("See https://example.org for details.") == ["See https://example.org for details."]


def test_comments_only_gives_empty_list() -> None:
    assert split("// only\n// comments\n") == []


# ---------------------------------------------------------------- draft shape


def test_draft_carries_text_position_and_paragraph_index() -> None:
    draft = split("Only one.")[0]

    assert draft == SegmentDraft(text="Only one.", position=0, paragraph_index=0)
