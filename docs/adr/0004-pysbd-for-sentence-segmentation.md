# 0004: pysbd for sentence segmentation

## Status
Accepted (2026-09-17)

## Context and problem
`domain.segmentation.split` turns a chapter into sentences (R2). Sentence boundaries in prose
are not trivial: abbreviations (`Mr.`, `St.`), quoted speech with attribution (`"Really?" she
asked.`), ellipses and decimals all contain terminal punctuation that must not split. The
34 tests in `tests/domain/test_segmentation.py` define the expected behaviour.

## Decision drivers
- Correct on the fixture (Conan Doyle: dialogue, abbreviations, proper names)
- Small dependency footprint; the domain layer must stay pure and fast to import
- Explainable in an interview; swappable behind `split()` without touching callers

## Considered options
- **A. pysbd** (rule-based port of pragmatic_segmenter, pure Python, no model). Measured on the
  17 hardest test strings: 15 correct; misses `c. 1854` and German single quotes `‚ ‘`.
  Last release 0.3.4 (2021); emits `SyntaxWarning` on Python 3.12 (non-raw regex strings).
- **B. spaCy** (`sentencizer` or `en_core_web_sm` parser). Maintained and standard, but ~100 MB of
  dependencies plus a model download in the Docker build, seconds of startup, and boundaries
  that can shift with model versions. Retake needs no other NLP in v1.0.
- **Null option: own implementation** (~100 lines: paragraphs, abbreviation list, quote handling).
  Fully explainable, no maintenance risk, but only as good as the cases we thought of.

## Decision
We choose **A, pysbd 0.3.4 pinned**, wrapped in `domain/segmentation.py`: nothing else imports
it. The two known gaps are closed by small tested helpers around the library (`_ascii_quotes`,
a length-preserving quote map so offsets apply to the original text, and
`_merge_split_abbreviations`). The `SyntaxWarning` is silenced for the `pysbd` module only.

## Consequences
- Good: no model, no download, import in milliseconds; 34 tests green on day one.
- Bad: maintenance risk. pysbd is effectively unmaintained; a future Python may turn the
  `SyntaxWarning` into an error.
- Known limitation: quoted speech followed by a capitalised attribution (`“Seven!” I answered.`)
  splits into two segments; `“Really?” she asked.` does not. Harmless for narration (a short
  pause), so accepted rather than guessed at with a verb list.
- Escape hatches, in order: vendor the single English rule file into `domain/`, or replace the
  library with the null option. Either is a change in one module; the tests are the contract.

## Confirmation
`tests/domain/test_segmentation.py` (behaviour) and `tests/domain/test_segmentation_helpers.py`
(the workarounds) must stay green; `pyproject.toml` pins `pysbd==0.3.4`.

## Interview explanation
Sentence splitting is a solved problem, so I used a small rule-based library instead of writing
my own or pulling in spaCy with a model. I measured it against my test cases first, wrapped the
two gaps in tiny functions, and kept the library behind one function so the tests, not the
library, define the behaviour. The known risk is that the library is unmaintained; the exit is
vendoring one file or replacing it, both local to one module.
