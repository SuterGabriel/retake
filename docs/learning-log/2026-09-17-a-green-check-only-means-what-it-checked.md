# A green check only means what it checked

Date: 2026-09-17 · Area: python | infra

## Initial mental model
Green is done. `ruff check .` says "All checks passed", pytest is green, so the code is clean.
And `except IntegrityError` around a commit is precise enough: the only constraint that can
fire on an import is the unique position, so any integrity error means "already imported".

## What failed
The python-reviewer agent found both wrong in one pass over Task 5.

1. `uv run ruff check .` reported "All checks passed!". `uv run ruff check . --no-cache`
   reported `I001 Import block is un-sorted` in `tests/services/test_projects.py`. The tests
   had been written before `retake.services` existed; ruff had classified the import as
   third-party, cached that verdict, and kept it after the module appeared. CI, with no cache,
   would have failed on the first push.
2. `services/projects.py` caught every `IntegrityError` on commit and raised
   `ProjectAlreadyImported` (HTTP 409). The same exception also covers the foreign key to
   `projects` and every CHECK constraint on `segments`. A real bug would have been reported to
   the client as a polite conflict. No test covered the branch, so it looked fine.

## Correct model
A check is a function of its inputs, and a cache is an input you did not choose. Trust a green
result only when you know what was checked and from what state; before calling a task done,
run tools from a clean state (`ruff check --no-cache`, `pytest -p no:cacheprovider`).
An `except` clause is a claim about which failure you expect; make it name that failure.
For database errors the constraint name is in the driver message, so
`_violates(exc, "uq_segments_project_id_position")` narrows the catch and everything else
propagates as the bug it is. A branch without a test is an untested claim; two `monkeypatch`
tests on `session.commit` now cover both sides.

## Decision applied
Commit `b131381` (`feat(api): POST /projects and POST /projects/{id}/import (TDD)`): narrowed
catch with `_violates`, two tests for the narrowing, `STATUS_BY_CODE` completeness test.
Working rule from now on: run `ruff check --no-cache` before a commit that adds new modules;
run the python-reviewer before showing a task as done.

## Interview explanation
A linter cache and an over-broad exception handler both showed green on a change that had a
real defect in each. The fix was procedural as much as technical: re-run checks from a clean
state, and make every `except` name the exact failure it expects and prove the branch with a
test. Green tells you a check passed; it does not tell you what the check saw.
