# Costs

What the bot's own requests to Claude cost, what was done about it on
2026-10-13, and what is left to decide. The model is `claude-haiku-4-5`
(US$1 a million tokens in, US$5 out; a cache write costs 1.25 times the
input price, a cache read a tenth of it).

`dev cost` gives the running figures (today against the daily limit,
this month, by task and by kind of request). This file is the audit.

## 1. What each kind of request costs (measured)

From the call log (`llm_calls`) of the live database, 11 and 12 October
2026: 42 requests, US$0.158. Averages for one request:

| Request | How many | In | From cache | To cache | Out | Cost each |
|---|---|---|---|---|---|---|
| Router | 20 | 2,163 | 0 | 0 | 95 | US$0.0026 |
| Extraction, pills | 12 | 521 | 4,627 | 2,545 | 103 | US$0.0047 |
| Extraction, timers | 7 | 504 | 1,503 | 3,971 | 87 | US$0.0061 |
| Extraction, channel | 2 | 1,845 | 0 | 0 | 58 | US$0.0021 |
| Chat | 1 | 2,329 | 0 | 0 | 5 | US$0.0024 |

The averages hide the two cases that matter, a request whose cached
part is still warm (asked again within five minutes) and one that is
cold:

| Extraction | Cached part | Cold (writes the cache) | Warm (reads it) | Cold, of all |
|---|---|---|---|---|
| Pills | about 7,400 tokens | US$0.0103 | US$0.0017 | 4 of 12 |
| Timers | about 5,500 tokens | US$0.0078 | US$0.0013 | 5 of 7 |

So one message costs, with the router's request and one extraction:

| A message | Cost |
|---|---|
| For pills, on its own (nothing asked in the last five minutes) | US$0.0131 |
| For pills, straight after another | US$0.0042 |
| For timers, on its own | US$0.0105 |
| A follow-up to an open card (no router) | US$0.0013 to US$0.0033 |
| A general question (the router, then chat) | US$0.0051 |
| A remark that gets no answer (the router alone) | US$0.0028 |
| A typed shortcut, a button, a reaction | nothing |

The three pills messages of 12 October were hours apart, so each was a
cold one at US$0.0131. That is the ordinary day: about four cents for
three doses said in words, a little over a dollar a month. The same
doses ticked off with a button cost nothing.

From the fixtures (the live eval, 13 October, after the changes below;
61 pills requests and 37 timers requests sent in a burst, so nearly all
warm): the router US$0.0028 each (2,229 in, 105 out, never cached),
pills extraction US$0.0019 each, timers extraction US$0.0016 each.

## 2. Prompt caching

**The minimum.** Anthropic's documentation (read 2026-10-13) gives
Claude Haiku 4.5 a minimum cacheable length of **4,096 tokens**. A
shorter prompt is processed without caching and no error is returned;
both cache figures in the usage come back as 0. That is what the log
shows:

| Prompt | Length | Cached? |
|---|---|---|
| Router (rules, catalogue of 4 tasks, tool) | about 2,160 tokens | **No: too short** |
| Chat (instructions and the list of shortcuts) | about 2,100 to 2,300 | **No: too short** |
| Extraction, channel | about 1,400 | **No: too short** |
| Extraction, bugs | about 1,650 | **No: too short** |
| Extraction, pills | about 6,600 | Yes |
| Extraction, timers | about 4,600 | Yes, with little to spare |

The cache marks on the short prompts are harmless and are left in
place: they start working by themselves if a prompt grows past the
minimum or the model changes.

**The order.** The cache holds a prefix: tools first, then the system
text, then the messages. What was already right: the router's rules and
catalogue are one fixed block, chat's instructions are one fixed block
with the time kept out of it (it goes in the message), and extraction's
tools were marked at the last tool.

**What changed (2026-10-13).** Extraction's instructions were one block
that differed with how the message came (a follow-up to a card, after a
list, after an answer, a reply), and the mark on the tools moved to
`not_this` on a follow-up. Now:

- the tools are marked at `none`, which every request to a task has;
  `not_this` comes after the mark
- the instructions are two blocks: the rules every request to the task
  shares (marked), then the few lines that depend on how the message
  came (not marked)

Every kind of request to a task now reads the same cached tools and
rules. The words Claude is given are the same; only where the marks sit
changed.

**The cost of a cold cache.** A cold request pays a quarter more for
the cached part than it would with no caching, and a warm one pays a
tenth. Caching wins once about one request in five is warm. Measured:
pills 8 warm of 12, timers 2 of 7 (QA bursts included), so it stays on;
but a day of single messages hours apart is all cold, and then caching
costs a quarter more than not caching. Worth looking at again with a
month of real use (`dev cost` shows tokens read from and written to
the cache).

## 3. What each request is sent

**Trimmed (2026-10-13).** Every action's schema carried the same two
long descriptions, of `guessed` and of `not_included`, which are also
explained in the instructions: nine times over for pills, ten for
timers. Each schema now names them in a line and the rule is said once,
in the instructions.

| Extraction | Tools and rules before | After | Saved |
|---|---|---|---|
| Pills | 25,958 characters | 22,992 | 11% (about 820 tokens a request) |
| Timers | 19,515 | 16,191 | 17% (about 915 tokens) |
| Bugs | 6,406 | 5,946 | 7% |
| Channel | 5,064 | 4,962 | 2% |

In money, by the prices above (an estimate from the sizes; the live run
below is the measurement):

| A message on its own | Before | After |
|---|---|---|
| For pills | US$0.0131 | about US$0.0120 |
| For timers | US$0.0105 | about US$0.0094 |

**Checked live** (allowed up to US$0.25; cost US$0.19 in all): the
pills fixtures gave 60 of 61, the same as before the change, with the
same known miss. The timers fixtures gave 36 of 37; the one miss
("pause it" came back with the timer's id rather than `@that`) is put
right by the code's own check, and there was no earlier timers run to
compare it with.

**Left as it is, and why.**

- **What the router is shown**: its rules, the catalogue (a name, an
  "only for" line and examples a task) and the last two exchanges. It
  is the dearest fixed cost (US$0.0026 on every routed message, never
  cached), and its rules are about 975 tokens of it. Rewording them
  could save a third of that, and could also change what it decides: it
  needs a full live eval, which is over the limit for tonight.
- **Chat's history**: the last 10 messages of plain chat, nothing a
  task said. One request in the log; nothing to trim.
- **The state sent to extraction**: capped at 20 lines a task a
  message already (`dev cost` reports how much was held back).
- **`pill_add` and `pill_edit`** describe the same fields twice (about
  4,800 characters each). Sharing the descriptions means rewording
  them: a candidate, with a live eval.

**`max_tokens`.** Output is only paid for when it is written, so these
are ceilings, not costs:

| Request | Ceiling | Written on average |
|---|---|---|
| Router | 200 | 95 to 105 |
| Extraction | 700 | 85 to 105 (a card of several pills is the most) |
| Chat | 1,024 | 5 to 22 |

Left as they are: none is near its ceiling, and a lower one saves
nothing unless it cuts an answer short, which would be worse.

## 4. Before and after, in one place

| | Before | After |
|---|---|---|
| Extraction's cached part shared by every kind of request to a task | Only the tools, by luck of the lookback | Tools and rules, by design |
| Pills extraction, cold | US$0.0103 | about US$0.0092 |
| Pills extraction, warm | US$0.0017 | about US$0.0016 |
| Timers extraction, cold | US$0.0078 | about US$0.0066 |
| Router | US$0.0026 | unchanged (too short to cache) |
| Chat | US$0.0024 | unchanged (too short to cache) |
| Pills fixtures right, live | 60 of 61 | 60 of 61 |

## 5. The daily spend line

`DAILY_SPEND_LIMIT_NZD` in `.env` (NZ$1.00 unless set; 0 switches it off;
until 2026-10-14 it was `DAILY_SPEND_LIMIT`, in US$). Costs are shown
in NZ$ and recorded in US$ (`core/money.py`): the figures in this file
are US$, as billed.
When a day's requests to Claude pass it, #bot-log is told once: "💰
Claude spend is over today's limit". Nothing is stopped. `dev cost`
shows today's spend against the limit. For scale: 11 October, a QA
evening, was US$0.13; 12 October US$0.03.

## 6. Candidates for free shortcuts (report only; none added)

From the message log, 5 to 12 October: 24 messages went through the
router on the live and dev databases. Only one exact phrase was said
more than once, so the candidates below are shapes, each of which went
to the same task every time:

| Shape | Times | Always went to | Cost each now | Note |
|---|---|---|---|---|
| "took `<pill>`", "taken my `<pill>`", "I took `<pill>` at `<time>`" | 9 | pills | US$0.0042 to US$0.0131 | The big one. A message that names one of my pills could skip the router (saves US$0.0026); read wholly in code it would be free. With reminders on, **Taken** is already free |
| "I took it at `<time>`" straight after a log | 3 | pills | US$0.0028 to US$0.0045 | Already skips the router within five minutes |
| "stop / end the pomodoro", "start pomodoro" | 3 | timers | US$0.0013 to US$0.0107 | `pomo` exists as a typed word; these could be other spellings of it |
| "channel reset", "clear channel" | 2 | channel | US$0.0046 | `reset channel` is the typed word; these are the same words another way round |
| "how long left on `<timer>`" | 1 (and 2 before the router) | timers | US$0.0105 | A typed `timer <name>` could answer it |

**Decided 2026-10-13:** "took `<pill>`" is now a typed shortcut, and
only that: the word and the pill's exact name, nothing else
(`tasks/pills/shortcut.py`). It costs nothing and is logged by the
same code as saying it. "took my `<pill>`", a time, or two pills are
read as before. No other shortcut is added, and the router is not
skipped for a message that merely names a pill.

What was weighed: a typed shortcut must carry its
task's name and a bare verb is never registered (`CLAUDE.md`), so "took
`<pill>`" as a shortcut would be a change to that rule; and the word
lists the code keeps are not meant to grow into the way something is
understood (`docs/BACKLOG.md`). Skipping the router when a message
names one of my own things keeps both rules and saves a fifth of an
isolated pills message.

**2026-10-13, after the self-test.** Two rules were added to what
every extraction is told (never complete a name; hand over what was
understood and leave out what was not said): about 170 tokens more in
the part that is cached, so a tenth of that price on every request
after the first.

The router's message gains one line (about 40 tokens) only when a
word typed could be part of the name of one of my things; nothing is
added to its rules, so every other message costs what it did.

The `schedule` task (2026-10-13) is one more line in the router's
catalogue, about 90 tokens on every routed message (the router is not
cached), and its own extraction rules when a message is its.

**2026-10-14, questions about the day (`DAY_QUESTIONS`).** With it on,
the router's catalogue gains a line for `weather` (about 100 tokens)
and the briefing's line is about 60 tokens longer: roughly US$0.0002
more on every routed message, since the router is not cached. The
answers themselves cost nothing: each is a template over what the
tasks keep. Both tasks' extraction prompts are short (under the
caching minimum), about US$0.002 a question, so a question costs
about US$0.005 in all, and a follow-up ("and this week?") about
US$0.002. Measured when the fixtures were recorded: 33 requests,
US$0.099, 33 of 33 right.

**2026-10-14, the understanding check-up.** The golden set is 59
requests now (US$0.19 a run). `python -m evals.live --part 1/2` runs
half of a file's fixtures (then `2/2`), so one run stays small: each
half cost US$0.08 to US$0.10. Before and after, with the pills
fixtures once (62 requests, US$0.13), came to US$0.50. One sentence
was added to `pill_edit`'s description (about 45 tokens in the
cached part of pills extraction).

**2026-10-14, a question never sticks.** A question asked within five
minutes of a task's answer is read by that task first and then goes
to the router all the same: one router request (US$0.0028) more than
before for a question the same task would have answered, and nothing
more when the router sends it back to that task (its reading is
used). Five fixtures recorded for it: US$0.022.

## 7. Questions (also in `docs/STATUS.md`)

1. Answered 2026-10-13: the router is not skipped; of the shortcuts,
   only "took `<exact pill name>`".
2. Reword the router's rules to shorten them, with a full live eval
   (about US$0.30 to US$0.50)?
3. A model with a lower caching minimum would cache the router and
   chat as well. That is a change of model, with its own prices and its
   own eval: only if you want it looked into.
