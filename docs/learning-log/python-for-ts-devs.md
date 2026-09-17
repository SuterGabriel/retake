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
(added via /explain-python)
