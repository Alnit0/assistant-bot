# Advisor context

**For the advisor** (Claude in claude.ai), fetched from GitHub at the start of every advisor conversation, beside `docs/ADVISOR.md`. It holds the design history, the interaction decisions and the planned features that are not in ADVISOR.md or `docs/RULES.md`.

Never write here: a real pill name, a real event name, a diary's words, a bot's display name, a location more precise than "Auckland", a token, topic, link or ID.

Last brought up to date: 22 Oct 2026, day (hub round 8).

---

## 1. Colour language (embed borders and box edges)

What each colour means, on an embed's border (round 7's hub, a routine's own card) and on a box's edge (round 8's hub):

- **Blue** (#5865F2): routines, repeating events, the diary
- **Green** (#57F287): done or taken
- **Red** (#ED4245): due
- **Yellow** (#FEE75C): notable or one-off events
- **Grey** (#4E5058): later, skipped (and missed)
- **Purple** (#9B59B6): AI tasks (the morning news, the gym)
- **Pink** (#EB459E): to-dos

In the code: `core/design.py` (`EMBED_COLOURS`). A task gives a status, never a colour.

## 2. Status indicators

**Not used in the hub from round 8** (22 Oct): there, state is said by text style (taken struck through with its time small, the next due bold, later plain) and by the box's edge colour. Elsewhere (a routine's own card, reminders), Unicode emoji squares only, no custom emoji:

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

## 5. The hub's design (round 8)

- **Round 8** (built 22 Oct, behind `DESIGN_ROUND=8`, preview "Design · Round 8"; not live until Alex says "ship round 8"): round 5's boxes with round 7's coloured edges. **One message**, nothing in it twice, kept in place all day and rewritten as things change.
- **The top**, outside any box: the date as the page title ("## Thursday 22 October"), then one small line "Next:" and the next thing still to come at its time.
- **💊 Pills** (only with doses today): round 3's dots and count on the heading; a dose a line in time order with a rule between ("Pill B · dose 1 of 2 · 11:00 am"). Taken: struck through, "taken 8:28 am" small under it. Skipped or missed: struck through, said small. The dose due (or, with none due, the next) bold with its one Taken; later doses plain. Edge: red with a dose due, green once all are dealt with and none missed, grey otherwise. Exact times only.
- **🗓️ Today** (only with events or routines today): events and routines in time order, never a dose ("Event · 8:00 am until 4:00 pm", "on now · until 4:00 pm", "Evening · 10:30 pm"); done or over struck and faint; on now and the next bold; one-off events in the next 7 days in one small line last. Edge: yellow with a one-off event today, blue otherwise. An event's own title, no emoji of ours.
- **To-dos** (only with open ones): pink, the first three, then "and N more". Done by words (no dropdown in round 8).
- **Last**, outside any box: one small line, "Diary streak 4 · 8 stories in #news" (the news part links to its message). No emoji.
- One emoji a box, on its heading; no squares anywhere in the hub. The pills checklist, the Today card and the to-dos card are not posted beside it. Too big for one message, the To-dos box is a second message; a box is never split. A hub message of another kind (round 7's embeds, an earlier layout) is posted fresh at the first change, the old one deleted. "Brief me" outside the hub shows the same message.
- **Round 7 (live since 21 Oct, 3:23 pm, `f525879`) is replaced by it**, because of Alex's words on 22 Oct: "Crammed, no text heirarchy used, no headings or dividers, Emojis feel misplaced, taken/later emoji feels out of place, card color does the same job better. Too cluttered". It also repeated itself: an embed a line of the day, then a Pills card and a Today card under it showing the same doses and events. Round 7 was two messages of embeds (the timeline with squares, then the to-dos and the diary); it stays selectable, as do rounds 5 and 6.
- **The morning news is one message in its own channel (for now), not in the hub** (Alex, 21 Oct: first "could each news article be its own card?", then, seeing the gaps between cards, "Can we simply combine the cards into one message?"). #news is a channel of its own beside the hub. One message a day, one purple embed a story, 8 at most: "<topic> · <outlet>" as the author line, the headline as the title linked to the article, the TL;DR as the description (about 30 words, 40 at most); no fields, no footer, no numbers. A fixed topic order (NZ politics, Housing and money, World news, World politics, Tech, AI, Web dev), an extra after its topic's first. Discord's 6,000 characters are for a message's embeds together: the longest TL;DRs shorten to fit, a headline never. Yesterday's deleted each morning; "another one" is a one-story message of its own. Earlier designs turned down: one embed with a numbered list, one embed with a field a topic, a message a story.
- **A message posted as a layout (rounds 4 to 6) can never take embeds, and one of embeds never becomes a layout.** On 21 Oct the 6 am briefing was round 5's, so after round 7 went live it read as plain lines all day. Since 22 Oct (not shipped yet) a hub briefing of another kind is posted again in the round's own kind at its first change.
- **Gone from the hub since round 7:** the Needs a look line (a problem still reaches him through the status line and a ping), the weather line, and yesterday's spend.

## 6. Planned features

- **The morning news** (live since 21 Oct, 10:07 pm, `a025112`, `READING_ENABLED=true`; the daily read and News headlines as one: "it makes sense to only have one set of news generated"): 39 feeds, a topic each; at 5:30 am one Haiku call picks 7 or 8 (a story each for world politics, NZ politics, world news, tech, AI, NZ housing and money, then 1 or 2 extras; web development a wildcard), a second writes the TL;DRs. Paywalled articles never picked; one US-only politics story a day unless asked for more. At 6 am the day's stories as one message in #news (live makes the channel beside the hub if it is missing; the dev bot never makes one), yesterday's deleted; the hub one line. No 👍 on the news: the picks learn from steering in words alone. Steering in #news, #inbox, a direct message or as a reply to the news (more like the housing one, more like the one about the water reform, less AI, skip housing tomorrow, more US politics, another one): a story is named by its words and Python finds it among today's headlines, asking which when none or several fit; Claude never picks it. Each TL;DR is tied to its story by the story's id. About NZ$0.04 a morning. It posts in a news channel Alex made in the hub's category (`NEWS_CHANNEL_ID`), its own channel for now: moving it into the hub as a message of its own is planned.
- **👍 as yes** (live since 21 Oct, 3:23 pm, `THUMBS_UP=true`): a registry of the messages that ask one simple yes (`core/thumbsup.py`), the 👍 through the bot's existing reaction path (`on_raw_reaction_add`, checked at once, a short quiet period, ✅, undo). On a dose's reminder it is Taken; on a reminder that went off or an expiry, Done; on a routine's own card, all of it done (the card turns green, 🟩 Done). It replaces the routines' dropdown; text still works.
- **Short state changes by edit** (not started; only when he asks): a message edited once to show a change, for example a routine's steps flipping from white to green squares on a 👍. Not animation.
- **An emoji for each event:** one Haiku call per new event title to pick one. On the list, not blocking.
- **Later:** money through Akahu, steps through a bridge from the phone, food logging (only if it would really be used).

## 7. Things Alex has turned down

- Custom emoji pictures for status indicators.
- Slash commands.
- Dropdowns for confirming a routine.
- Emoji floating in inline fields (it looked odd).
- A proposed new name for the bot (it has another now; the names are never written in the docs).
- A 👍 on the news ("Perhaps we disregard the thumb system for news?", 21 Oct), and a message a news story (the gaps between them looked bad).
- Animation by editing a message over and over (21 Oct, the lab grid): about one frame a second at best, too choppy. "It works, the animation isn't really anywhere as good as I had hoped. It may have applications for notifying or changing things but not animating".
- Round 7's hub of embeds (22 Oct): "Crammed, no text heirarchy used, no headings or dividers, Emojis feel misplaced, taken/later emoji feels out of place, card color does the same job better. Too cluttered". The status squares in the hub went with it (round 8).
- The feature freeze, called off on 21 Oct: "I feel like we're wasting development time, I'm using the bot daily and I have a list of changes I want made".

## 8. Maintaining this file

At the end of every batch, update this file alongside ADVISOR.md: new design decisions, changes to how things are done, planned features, and anything the advisor discussed with Alex. Keep it under 150 lines, with the same privacy rules as ADVISOR.md. Commit it with the batch.
