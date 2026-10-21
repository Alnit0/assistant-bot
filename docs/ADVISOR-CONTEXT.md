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
- **Purple** (#9B59B6): AI tasks (news, gym, the daily read)
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
- **Message 2 (tracking):** the to-dos in pink, the diary's streak in blue. Not sent when there is neither. Both messages are rewritten in place all day.
- "Brief me" outside the hub shows message 1 only.
- **Gone from the old briefing:** the Needs a look line (a problem still reaches him through the status line and a ping), the weather line, and yesterday's spend.
- Behind `DESIGN_ROUND=7`, built and pushed (`d327729`), not live: live is still on round 5.

## 6. Planned features

- **News headlines** (designed, not built): from RSS, 30 to 50 feeds, one Haiku call a day to pick the 5 to 8 best. Categories: NZ news, NZ business, world, politics, tech, web and development, science. A purple embed in the hub's message 2.
- **👍 as yes** (built and pushed 21 Oct, `b2fa0a4`, behind `THUMBS_UP`, not live): a registry of the messages that ask one simple yes (`core/thumbsup.py`), the 👍 through the bot's existing reaction path (`on_raw_reaction_add`, checked at once, a short quiet period, ✅, undo). On a dose's reminder it is Taken; on a reminder that went off or an expiry, Done; on a routine's own card, all of it done (the card turns green, 🟩 Done). It replaces the routines' dropdown; text still works.
- **An emoji for each event:** one Haiku call per new event title to pick one. On the list, not blocking.
- **Later:** money through Akahu, steps through a bridge from the phone, food logging (only if it would really be used).

## 7. Things Alex has turned down

- Custom emoji pictures for status indicators.
- Slash commands.
- Dropdowns for confirming a routine.
- Emoji floating in inline fields (it looked odd).
- A proposed new name for the bot (it has another now; the names are never written in the docs).
- The feature freeze, called off on 21 Oct: "I feel like we're wasting development time, I'm using the bot daily and I have a list of changes I want made".

## 8. Maintaining this file

At the end of every batch, update this file alongside ADVISOR.md: new design decisions, changes to how things are done, planned features, and anything the advisor discussed with Alex. Keep it under 150 lines, with the same privacy rules as ADVISOR.md. Commit it with the batch.
