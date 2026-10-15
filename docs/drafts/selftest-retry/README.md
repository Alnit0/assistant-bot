# Draft: a self-test step Discord got in the way of is run once more

Not applied yet (the self-test was running when it was written, 16 Oct).
To apply, from the repo root, with no self-test running:

1. `python docs/drafts/selftest-retry/patch_retry.py`: the harness's `step`
   becomes a loop of attempts (`Attempt`), a step that fails while Discord
   answers 5xx or a rate limit is run once more after 10 s, and failing so
   again is `discord` (Discord unavailable): no D bug, not counted as
   failed, said in the run summary and the report. Also add `import re` to
   `selftest/harness.py`.
2. `python docs/drafts/selftest-retry/rewrite_steps.py selftest/phases.py selftest/day.py`:
   every `async with h.step(...):` becomes `async for attempt in h.step(...):`
   with `async with attempt:` and the body indented four more.
3. Tests for the retry and the new status, then this folder goes.
