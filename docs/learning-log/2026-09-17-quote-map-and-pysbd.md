# Typographic quotes broke sentence splitting; the fixture found it, the tests had not

Date: 2026-09-17 · Area: python

## Initial mental model
Map every typographic quote to its ASCII cousin (`“ ”` → `"`, `‘ ’` → `'`) with a
length-preserving `str.translate`, hand the ASCII copy to pysbd, slice the original text by
the returned offsets. Symmetric, obvious, done. All 34 behaviour tests were green.

## What failed
The smoke test on `fixtures/chapter-clean.txt` listed a segment that was only `”`. The
paragraph has a single-quoted phrase inside double-quoted speech:

```
“… the sentence—‘This account of you we have from all quarters received.’ A Frenchman …
… to resolve all our doubts.”
```

Version 1 of the map (`‘` → `"`, `’` → `'`, chosen so `don’t` stays a word) unbalanced the
quotes; pysbd lost track and detached the final `”` as its own "sentence". Version 2, the
symmetric map (`‘ ’` → `'`), balanced them but pysbd then refused to split after
`received.' A Frenchman`, because an ASCII apostrophe can be part of a word. Neither map
alone was correct; the fixture case was not in the tests.

## Correct model
pysbd only recognises ASCII double quotes as speech delimiters, and treats `'` as ambiguous.
The map must therefore be asymmetric on purpose: opening single quotes become `"`, the closing
`’` stays `'`. The imbalance that this creates is repaired after splitting by two small pure
functions, each with its own tests: `_reattach_leading_closing_quotes` moves a closing quote
that pysbd pushed to the start of the next sentence back where it belongs, and
`_merge_dangling_fragments` attaches a "sentence" without any letter or digit to its neighbour.
General rule: wrap a third-party heuristic in your own pre- and post-processing and test those
pieces separately; do not tune the library.

## Decision applied
Commit `b4e5e11` (`feat(api): sentence segmentation with pysbd (TDD)`), ADR-0004. The smoke
test now reports 0 segments without a word character and 0 starting with a closing quote.
A test for the nested-quote paragraph was added to `tests/domain/test_segmentation.py`.

## Interview explanation
My unit tests covered every quote style I could think of, and the first real chapter still
produced a segment consisting of one closing quote. The fix was not a cleverer regex but an
explicit, asymmetric mapping plus two tiny repair functions with their own tests. Real input
finds the cases you did not imagine, so a smoke test on a fixture belongs next to the unit tests.
