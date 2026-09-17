# Metrics

All numbers are measured, not estimated. Update this file whenever the numbers change; keep the history.

## Detection quality (planted-defect fixture, `fixtures/chapter-defects.json`)

| Type | Planted | Found | False alarms | Recall | Precision | Date |
|---|---|---|---|---|---|---|
| omission | 8 | | | | | |
| repetition | 5 | | | | | |
| substitution | 5 | | | | | |
| truncation | 2 | | | | | |

## Cost

| Metric | Value | Date |
|---|---|---|
| Credits per accepted audio minute (first pass) | | |
| Credits for fixing 20 defects, sentence retakes | | |
| Credits for the same fixes, paragraph regeneration (computed) | | |
| Savings ratio | | |

## Time

| Metric | Value | Date |
|---|---|---|
| Wall time to generate 5k-word chapter (concurrency = N) | | |
| Review time to clear 20 findings with the keyboard workflow | | |
| Baseline: listening through the whole chapter | | |

## How to reproduce
`make metrics` (to be written in week 9) runs the fixture end-to-end against a mocked ElevenLabs adapter for detection numbers, and prints the ledger for cost numbers from the last real run.
