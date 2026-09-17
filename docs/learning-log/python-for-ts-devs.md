# Python for TypeScript developers

Grows as the project progresses. Each section: what it is, TS equivalent, where the analogy breaks.

## Quick map
| TypeScript | Python 3.12 | Watch out |
|---|---|---|
| `interface` | `Protocol` / `TypedDict` / Pydantic model | pick by purpose: behaviour, dict shape, runtime validation |
| `type A = B \| C` | `type A = B \| C` | hints are not enforced at runtime |
| `undefined`/`null` | `None` | `str \| None` is explicit |
| Zod schema | Pydantic `BaseModel` | validates at runtime |
| DTO interface | `@dataclass` | no runtime parsing |
| `Promise<T>` | `Coroutine[..., T]` | must be awaited or scheduled; nothing runs until then |
| structural typing | `Protocol` | opt-in, explicit |
| `readonly` | `frozen=True`, tuples | conventions, not enforcement |
| npm + lockfile | uv + `pyproject.toml` + `uv.lock` | uv also manages the interpreter |
| ESLint + Prettier | Ruff | one tool |
| `tsc --noEmit` | mypy / pyright | annotations only; no runtime effect |

## Entries

### uv, pyproject.toml and the virtual environment (week 1, task 1)

`pyproject.toml` is `package.json`: name, version, `dependencies`, and `[dependency-groups] dev`
for dev dependencies. It also holds tool config (`[tool.ruff]`, `[tool.mypy]`) where TS uses
separate `.eslintrc` / `tsconfig.json` files. `uv.lock` is `package-lock.json`. `.venv/` is
`node_modules/`, with one difference: Node finds `node_modules` automatically, Python needs the
venv activated. `uv run <cmd>` does that for one command, like `npx` or an npm script.

| TypeScript | uv | Notes |
|---|---|---|
| `npm install` | `uv sync` | resolves, updates the lockfile if needed, installs |
| `npm ci` | `uv sync --locked` | installs from the lockfile; **fails** if pyproject and lock disagree. Use in CI. |
| (no equivalent) | `uv sync --frozen` | installs from the lockfile without checking. Use in Docker builds. |
| `npx tsc` | `uv run mypy src` | runs inside the venv |
| nvm | built in | `.python-version` + `requires-python`; uv downloads the interpreter |

**Why `--locked` in CI:** CI must test the commit, not something it resolved itself. If the lockfile
is out of date, CI should fail loudly instead of quietly repairing and hiding it. Same principle as a
CI step that must not swallow a failing `alembic upgrade`.

**src layout:** code lives in `src/retake/`, not `retake/`. Tests then import the *installed*
package from the venv (an editable install, like `npm link` to yourself), never the folder that
happens to be in the working directory.

**Where the analogy breaks:** no `exports` map, no bundling. A package is a folder with
`__init__.py`, and `import retake.config` is a file path. One venv per project, no nested
`node_modules`; version conflicts are resolved, not duplicated.

### Docker multi-stage builds (week 1, task 2)

Several `FROM` lines = separate build and runtime steps. Stage 1 installs (like running `tsc` with
devDependencies present), stage 2 starts from a slim base and copies only the result (`.venv`),
like `node dist/main.js` without devDependencies. Each layer is cached independently, so copy
`pyproject.toml` + `uv.lock` and install first, and copy source code afterwards: a code change
then never repeats the dependency install. Same pattern as `COPY package*.json` + `npm ci` before
`COPY .`. In dev, compose bind-mounts `./apps/api` over the image so `--reload` sees edits; the
image provides the environment, the mount provides the code.
