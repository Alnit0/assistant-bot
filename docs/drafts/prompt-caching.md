# Prompt caching for the bot's own requests (draft, 17 Oct, late)

Low priority, for the next batch: nothing of it is built or shipped. The
ask: measure each prompt, put what never changes first, mark it for the
cache wherever it reaches Haiku 4.5's minimum of 4,096 tokens (merging
shared parts if that brings more over the line), the 5-minute cache by
default, the 1-hour one only where a run spans longer and it saves money
overall; cache hits and misses in the cost records; after a week, the
real saving in NZ$ against the week before. No behaviour change: every
recorded check still passes.

## Measured (17 Oct, 11:20 pm, `python -m evals.prompt_sizes`)

The prefix is the tools and the system text, everything before the
message, counted by Anthropic's token counter (free, nothing sent to a
model), with every switch live has on.

| Prompt | Prefix tokens | Over 4,096? |
|---|---|---|
| Router | 4,737 | yes (cached today) |
| Smart inbox, sort | 4,075 | **21 short** |
| Daily read, pick and TL;DR | 1,102 | no |
| Extraction · pills | 8,781 | yes (cached today) |
| Extraction · personal routines | 7,170 | yes (cached today) |
| Extraction · calendar | 6,264 | yes (cached today) |
| Extraction · reminders | 5,927 | yes (cached today) |
| Extraction · timers | 5,191 | yes (cached today) |
| Extraction · schedule | 3,888 | no |
| Extraction · to-dos | 3,690 | no |
| Extraction · plan my day | 3,583 | no |
| Extraction · birthdays | 3,462 | no |
| Extraction · diary | 3,422 | no |
| Extraction · daily read | 3,263 | no |
| Extraction · bugs | 2,779 | no |
| Extraction · briefing | 2,718 | no |
| Extraction · weather | 2,074 | no |
| Extraction · channel | 1,927 | no |

## What is already so

- **The order is right** (docs/COSTS.md, section 2): the tools first,
  then the system text that never changes (marked), then what depends on
  how the message came, and the message last.
- **The marks are there**: the router, the inbox, the read and every
  extraction carry `cache_control` on their unchanging part. Under the
  minimum a mark does nothing and costs nothing.
- **Hits and misses are recorded**: `llm_calls` keeps the tokens read
  from and written to the cache for every request, and `dev cost` adds
  them up. The weekly report can be made from that table alone.

## What could be done, cheapest first

1. **The smart inbox**: 21 tokens short. Moving the one line of the
   rules that names the time into the message (it changes each request)
   would shorten the prefix; the other way is the rules for files,
   which every request carries, staying in the prefix. Only worth it if
   inbox requests come within 5 minutes of each other often enough
   (about one in five warm pays for the cold ones).
2. **Extraction's shared rules**: every task's extraction carries the
   same general rules, but the tools come before the system text in the
   cache's order and they differ from task to task, so the shared rules
   can't be one prefix for all. Merging tasks' prompts would change what
   Claude is told: not a "no behaviour change" job.
3. **The 1-hour cache for the self-test and the nightly**: they run on
   recorded answers almost always (and this month's self-test spend is
   over its cap), so there is nothing to save there now.

## What to decide with a week of real use

A day of single messages hours apart is all cold, and then caching costs
a quarter more for the cached part than none would. The saving depends
on how often requests to the same task come within 5 minutes. The
report after a week: per prompt, requests, warm share, and NZ$ with and
without the marks, from `llm_calls`.
