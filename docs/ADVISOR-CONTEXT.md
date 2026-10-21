# Advisor context

**For the advisor** (Claude in claude.ai), fetched from GitHub at the start of every advisor conversation, beside `docs/ADVISOR.md`. It holds the design history, the interaction decisions and the planned features that are not in ADVISOR.md or `docs/RULES.md`.

Never write here: a real pill name, a real event name, a diary's words, a bot's display name, a location more precise than "Auckland", a token, topic, link or ID.

Last brought up to date: 21 Oct 2026, evening.

---

## 1. Colour language (embed border colours)

What each border colour means, everywhere an embed is used (round 7's hub, a routine's own card):

- **Blue** (#5865F2): routines, repeating events, the diary
- **Green** (#57F287): done or taken
- **Red** (#ED4245): due
- **Yellow** (#FEE75C): notable or one-off events
- **Grey** (#4E5058): later, skipped (and missed)
- **Purple** (#9B59B6): AI tasks (the morning news, the gym)
- **Pink** (#EB459E): to-dos

In the code: `core/design.py` (`EMBED_COLOURS`). A task gives a status, never a colour.

## 2. Status indicators

Unicode emoji squares only, no custom emoji:

- 🟩 Taken, with the time inline: "🟩 Taken 8:12 am"
- 🟥 Due
- ⬜ Later
- ⏭️ Skipped
- ⬛ Missed
- 🟩 Done (for routines)

## 3. Discord embed constraints

- An embed has a 4px coloured left border, a bold title, description text, fields (inline or not) and a small footer.
- No CSS, no custom backgrounds, no font control.
- At most 10 embeds a message (any number of messages a channel).
- Inline fields render side by side, up to 3 a row, each with its bold name above its value.

## 4. Interaction design decisions

- Alex uses the bot mostly on his phone.
- **A double-tap 👍** is the preferred confirmation gesture (Discord mobile: Settings > Chat > Gestures). The emoji cannot be changed: it is always 👍.
- Text replies always work as well, beside reactions.
- Dropdowns are coming off routines, replaced by the 👍.
- For less common actions (skip, snooze), a long-press reaction by hand is fine.
- Slash commands were turned down: the / key is awkward on a phone, and the Apps menu is hard to find on a computer.
- Custom emoji pictures for status badges were turned down: "These feel silly, we could just use red, green and grey squares".

## 5. The hub's design (round 7)

- **Two messages**, because of the 10-embed limit.
- **Message 1 (the timeline):** the date as its text, then an embed a thing in time order. At the same time: events first, then doses, then routines. Repeating events blue, notable ones yellow. Doses coloured by their state, with the time taken inline. Routines blue. Over ten, the tenth embed becomes a grey "More today" of the rest.
- **Message 2 (tracking):** the to-dos in pink, the diary's streak in blue, then the morning news's one line in purple ("📰 8 stories in #news", its title opening the day's news message). Sent when any of them has something, the news's line alone included. Both messages are rewritten in place all day.
- **The morning news is one message in its own channel (for now), not in the hub** (Alex, 21 Oct: first "could each news article be its own card?", then, seeing the gaps between cards, "Can we simply combine the cards into one message?"). #news is a channel of its own beside the hub. One message a day, one purple embed a story, 8 at most: "<topic> · <outlet>" as the author line, the headline as the title linked to the article, the TL;DR as the description (about 30 words, 40 at most); no fields, no footer, no numbers. A fixed topic order (NZ politics, Housing and money, World news, World politics, Tech, AI, Web dev), an extra after its topic's first. Discord's 6,000 characters are for a message's embeds together: the longest TL;DRs shorten to fit, a headline never. Yesterday's deleted each morning; "another one" is a one-story message of its own. Earlier designs turned down: one embed with a numbered list, one embed with a field a topic, a message a story.
- "Brief me" outside the hub shows message 1 only.
- **Gone from the old briefing:** the Needs a look line (a problem still reaches him through the status line and a ping), the weather line, and yesterday's spend.
- Behind `DESIGN_ROUND=7`: live since 21 Oct, 3:23 pm (`f525879`), with `THUMBS_UP=true`.

## 6. Planned features

- **The morning news** (live since 21 Oct, 10:07 pm, `a025112`, `READING_ENABLED=true`; the daily read and News headlines as one: "it makes sense to only have one set of news generated"): 39 feeds, a topic each; at 5:30 am one Haiku call picks 7 or 8 (a story each for world politics, NZ politics, world news, tech, AI, NZ housing and money, then 1 or 2 extras; web development a wildcard), a second writes the TL;DRs. Paywalled articles never picked; one US-only politics story a day unless asked for more. At 6 am the day's stories as one message in #news (live makes the channel beside the hub if it is missing; the dev bot never makes one), yesterday's deleted; the hub one line. No 👍 on the news: the picks learn from steering in words alone. Steering in #news, #inbox, a direct message or as a reply to the news (more like the housing one, more like the one about the water reform, less AI, skip housing tomorrow, more US politics, another one): a story is named by its words and Python finds it among today's headlines, asking which when none or several fit; Claude never picks it. Each TL;DR is tied to its story by the story's id. About NZ$0.04 a morning. It posts in a news channel Alex made in the hub's category (`NEWS_CHANNEL_ID`), its own channel for now: moving it into the hub as a message of its own is planned.
- **👍 as yes** (live since 21 Oct, 3:23 pm, `THUMBS_UP=true`): a registry of the messages that ask one simple yes (`core/thumbsup.py`), the 👍 through the bot's existing reaction path (`on_raw_reaction_add`, checked at once, a short quiet period, ✅, undo). On a dose's reminder it is Taken; on a reminder that went off or an expiry, Done; on a routine's own card, all of it done (the card turns green, 🟩 Done). It replaces the routines' dropdown; text still works.
- **Animated progress grid** (Alex, 21 Oct: "let's get a basic command that displays something"): a proof of concept is built behind `LAB_GRID`, on the dev bot only: "lab grid [seconds]", a 5 by 5 grid of square emoji in one message, edited frame by frame (black, a diagonal rainbow wave, green). The real use to follow: a grid that fills while the bot works on something slow (the smart inbox reading a file, the gym logbook import) and then becomes the answer.
- **An emoji for each event:** one Haiku call per new event title to pick one. On the list, not blocking.
- **Later:** money through Akahu, steps through a bridge from the phone, food logging (only if it would really be used).

## 7. Things Alex has turned down

- Custom emoji pictures for status indicators.
- Slash commands.
- Dropdowns for confirming a routine.
- Emoji floating in inline fields (it looked odd).
- A proposed new name for the bot (it has another now; the names are never written in the docs).
- A 👍 on the news ("Perhaps we disregard the thumb system for news?", 21 Oct), and a message a news story (the gaps between them looked bad).
- The feature freeze, called off on 21 Oct: "I feel like we're wasting development time, I'm using the bot daily and I have a list of changes I want made".

## 8. Maintaining this file

At the end of every batch, update this file alongside ADVISOR.md: new design decisions, changes to how things are done, planned features, and anything the advisor discussed with Alex. Keep it under 150 lines, with the same privacy rules as ADVISOR.md. Commit it with the batch.
