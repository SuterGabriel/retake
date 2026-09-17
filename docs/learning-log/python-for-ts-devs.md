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

### The savepoint pattern in database tests (week 1, task 3)

`tests/test_db_invariants.py::session` opens one connection, starts an outer transaction that
is never committed, and hands the test a session that works inside it. With
`join_transaction_mode="create_savepoint"` the session does its work on a SAVEPOINT (a
transaction inside the transaction). When a `flush()` fails with `IntegrityError`, Postgres marks
the running transaction as aborted and ignores every further statement until a rollback. Without
a savepoint that would poison the outer transaction; with one, the session rolls back to the
savepoint and the outer transaction stays usable. `outer.rollback()` at the end discards
everything the test wrote, so tests leave no state behind and need no cleanup code.

| Python | TypeScript | Notes |
|---|---|---|
| `@pytest.fixture` with `yield` | `beforeEach` + `afterEach` in one function | code before `yield` is setup, after it teardown; teardown runs even if the test fails |
| `async with engine.connect() as conn` | `await using conn = ...` (TS 5.2) or `try/finally` + `release()` | context managers are built-in `try/finally` |
| `outer = await conn.begin()`, never committed | Prisma `$transaction(async tx => { ...; throw })` to discard | Prisma forces the callback; SQLAlchemy lets you hold the transaction |
| `join_transaction_mode="create_savepoint"` | Knex `trx.savepoint()`; Prisma has none | **analogy breaks**: Prisma has no nested transactions |
| `AsyncIterator[AsyncSession]` return type | `AsyncGenerator<AsyncSession>` | the fixture is a generator pytest drives exactly once |
| `with pytest.raises(IntegrityError, match="ux_...")` | `await expect(fn()).rejects.toThrow(/ux_.../)` | `match` is a regex on the message |

**Surprises for TS developers**
1. A failed statement poisons the whole Postgres transaction ("current transaction is aborted,
   commands ignored until end of transaction block"). "Catch and carry on" does not exist here;
   savepoints are the only answer. This is database behaviour, not a language feature.
2. `session.add()` never talks to the database. The `IntegrityError` appears at `flush()`, when
   the SQL is sent. In Prisma the error appears at the `await` of `create()`. Wrapping
   `pytest.raises` around `add_all` instead of `flush` gives a green test that checks nothing.
3. `yield` inside a fixture is not an iterator for you: same keyword as a generator function, but
   pytest drives it, once for setup and once for teardown.

**Question to answer without notes:** why does `await session.flush()` raise the
`IntegrityError` rather than `session.add_all(...)`, and what would happen to the
`outer.rollback()` at the end if the fixture used no savepoint?
