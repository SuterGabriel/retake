---
name: learning-log
description: Draft a learning-log entry in docs/learning-log/ from something that just went wrong or was newly understood. Use when the developer says "/learning-log" or after a debugging session that corrected a mental model.
---

# Learning-log entry

1. Copy `docs/learning-log/0000-template.md` to `docs/learning-log/YYYY-MM-DD-short-title.md`.
2. Fill the five sections from the conversation so far: initial mental model, what failed (with the actual error), the correct model, the decision applied (commit or ADR link), and a 3-sentence interview explanation.
3. Keep it under 40 lines. Facts over prose. Do not invent details the developer did not experience.
4. Show the draft; the developer edits and commits it. Never commit on their behalf.
