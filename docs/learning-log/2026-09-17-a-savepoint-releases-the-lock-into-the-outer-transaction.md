  # A savepoint releases the lock into the outer transaction

Date: 2026-09-17 · Area: sqlalchemy | async

## Initial mental model
`async with session.begin_nested():` is a scope. Whatever happens inside, including a
`SELECT ... FOR UPDATE`, ends when the block ends, like a `using` block or a mutex held only
inside a function. So `return existing` from inside the block was harmless: the savepoint is
released, the lock with it. And `session.rollback()` is the clean way to end a refused
reservation: nothing written, transaction over.

## What failed
Two things, found by the python-reviewer with all 165 tests green.

1. RELEASE SAVEPOINT does not release row locks. Locks belong to the *transaction*; releasing
   a savepoint hands its locks up to the outer transaction, and only COMMIT, ROLLBACK or
   ROLLBACK TO SAVEPOINT lets them go. My early `return` skipped the `commit()` after the
   block, so a duplicate-delivered job kept the `budget_periods` row locked until its session
   closed, possibly after a 60-second ElevenLabs call. Every other worker's `reserve()` would
   have queued behind it. The savepoint test fixture could not show this: it never commits for
   real, so nothing ever observes the lock from outside. The reviewer proved it with a second
   session: `SELECT ... FOR UPDATE NOWAIT` on the period row raised `LockNotAvailable`.
2. The fix's first version ended the refusal path with `session.rollback()`. Two tests then
   died with `MissingGreenlet: greenlet_spawn has not been called`. A rollback expires every
   ORM object in the session; the test's next `project.id` triggered a lazy reload, which in
   async SQLAlchemy is an implicit await in a place that cannot await.

## Correct model
- A row lock is transaction-scoped. Every exit path of a function that takes one must end the
  transaction: commit, or roll back to a savepoint that *contains* the lock.
- `begin_nested()` is still the right tool for the locked section, because ROLLBACK TO
  SAVEPOINT does release the locks taken inside it while leaving the outer transaction and
  the caller's objects untouched. After that, `commit()` on the (now empty) outer transaction
  ends it cleanly; `rollback()` would expire everything the caller holds.
- A savepoint-per-test fixture is perfect for isolation and useless for lock behaviour.
  Anything about locks needs two real sessions and `NOWAIT` (or `lock_timeout`) to observe.

## Decision applied
Commit "feat(api): LedgerService with pending reservations, idempotency and local budget":
idempotency lookup before any lock, locked section in a savepoint, `commit()` on every path,
`lock_timeout = 5s` mapped to `LedgerLocked`, and two two-session tests
(`test_duplicate_reserve_does_not_keep_the_period_locked`,
`test_budget_exceeded_does_not_keep_the_period_locked`) that lock the row with `NOWAIT` from
a second session after each refusal path.

## Interview explanation
I took a row lock inside a savepoint and returned early, assuming the lock ended with the
block; it did not, because locks are transaction-scoped and releasing a savepoint just hands
them upward. My isolated test fixture could never see it; a second session with
`FOR UPDATE NOWAIT` did. The fix is to end the transaction on every path, using a savepoint
rollback to drop the lock and an empty commit instead of a rollback so the caller's ORM objects
are not expired, which in async code would surface as a MissingGreenlet on the next attribute.
