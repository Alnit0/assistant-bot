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

## Added 17 Oct, late: the 1-hour cache kept warm, and fast paths

**(1) The 1-hour cache with a keep-warm read** about every 55 minutes
from 7 am to 11 pm (about 18 reads a day a prompt), turned on only if a
week's numbers show it saves money overall.

Live's last 7 days (`llm_calls`, read only): 83 requests to Claude,
US$0.36 (about NZ$0.62). Pills' extraction 23 requests (US$0.15, 94,601
tokens written to the cache, so about 11 cold), the router 37 (US$0.12,
none cached: its prefix was under the minimum until tonight's tasks
took it to 4,737), timers 9, calendar 7, channel 5, bugs 1, chat 1.

Projected at Haiku 4.5's prices (input US$1, a 1-hour cache write US$2,
a cache read US$0.10, a million tokens):

| Prompt | Keep-warm a week | Saved a week if every request were warm | Net |
|---|---|---|---|
| Pills' extraction (8,781 tokens) | about US$0.23 | about US$0.11 (11 cold writes) | **loses** about NZ$0.20 |
| The router (4,737 tokens) | about US$0.13 | about US$0.16 against no cache, less against the 5-minute cache it now gets | about even |

At about five requests a day, a keep-warm read costs more than it saves.
**Projected: no saving; left off.** Decided after a week of the router
on the 5-minute cache (it starts caching with tonight's ship), from that
week's `llm_calls`.

**(2) Fast paths for frequent phrasings**, from the last 14 days of live
messages that reached Claude (read only; nothing of the messages is
written here): 158 messages, US$0.72 (about NZ$1.23), most of them on
the old way of sending every tool, from before the router (13 to 15
Oct), and most of them testing. **No phrasing came more than 3 times**;
the repeated ones were a joke for chat (3), a channel's clearing in
other words (3, about US$0.02), a test word (2), "keep me" and "pin me"
(2 each), a reply of yes or skip (2 each, which only a card or the task
that just answered can read), a timer by its id (2), help for a word
(2), and a pill taken at a time (2: the pills task's own, which a
shortcut already covers for an exact name and no time).

The one safe fast path: the channel's reset said as "clear channel",
which the `reset channel` word does at no cost and which always asks
first on a card. Projected saving: about US$0.01 a fortnight (NZ$0.02).
Yes, skip and the rest are not safe for code: they mean different things
on different cards. **Projected overall: under NZ$0.05 a month.** To
build next batch with its golden test (an exact keyword, as the rules
allow), and to look again at a month of router-era messages.

**Actual saving**: reported a week after each change ships, from
`llm_calls` against the week before, in NZ$.
