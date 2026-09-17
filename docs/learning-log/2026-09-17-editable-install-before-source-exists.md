# Editable install built before the source folder existed

Date: 2026-09-17 · Area: python

## Initial mental model
`uv sync` is `npm install`: run it once after writing `pyproject.toml`, then write code. The
project package would be importable because it is listed in pyproject, like a workspace package
in npm.

## What failed
`uv sync` ran before `src/retake/` existed. Later, `uv run pytest` failed with:

```
ImportError while loading conftest 'C:\retake\apps\api\tests\conftest.py'.
E   ModuleNotFoundError: No module named 'retake'
```

`uv pip list` showed `retake 0.1.0` installed, and `retake-0.1.0.dist-info/` existed in
`site-packages`, but no `_editable_impl_retake.pth` file. A second `uv sync` did nothing
("Checked 50 packages"), because from the lockfile's point of view nothing had changed.

## Correct model
An editable install is not a symlink to the project. The build backend (hatchling) builds a
tiny wheel at install time that contains a `.pth` file pointing at `src/`. If the package folder
does not exist at build time, that wheel is built without it. uv then considers the project
installed and will not rebuild it until the project itself is marked changed. The fix is
`uv sync --reinstall-package retake`. TS equivalent: `npm link` to a package whose `main` file
does not exist yet.

## Decision applied
Order in the scaffold task: write `pyproject.toml` *and* the package skeleton, then `uv sync`.
No rule needed; documented here and in `docs/learning-log/python-for-ts-devs.md`.

## Interview explanation
An editable install is a build artefact that records where the source lives, produced once at
install time. If the source is missing at that moment, the artefact is empty and later syncs will
not repair it because the lockfile has not changed. Reinstalling the project package rebuilds it.
