# Now

What is happening this minute. Updated after every step of a batch;
history is `docs/STATUS.md`. Read first, with `/catchup`.

**Idle**, last batch was overnight 16 Oct: calendars from several
sources and adding to the Bot calendar, a day in the hub with
everything on, 41 golden conversations, a health check. All on live.

**Live:** `68b954e` since 16 Oct, 9:31 am (one restart, no errors):
closing bugs in words, Needs a look's plain bug lines, questions 91 and
92. D1 (the 3:30 am nightly, 20 steps) was the self-test's own switch
list, fixed; the dev-bot self-test before the ship 150 of 150. **Next:**
the 3:30 am nightly on 17 Oct, its result checked and reported (D1
should close by itself)

**Drafts and worktrees:** `docs/drafts/gym-onboarding.md`; three old
worktrees, all merged

**Waiting on Alex**
- **Calendar ids:** his events still come from the iCal link (the Gmail
  calendar showed 1 event against 5 that week). Once he knows which
  calendar they are on, list them in live's `.env`, comma apart:
  `CALENDAR_READ=google:<that calendar's id>,google:CALENDAR_BOT_ID`,
  then one restart, then the iCal link goes (`docs/GOOGLE-SETUP.md`)
- Round 5 item by item (Q68 to Q75 in its post)
- The daily read: his look at its post, and questions 86 to 90
- Questions 76 to 79 (gym), 63, 24 to 28
- QA item 0 (direct messages)
- Close B2 and B5: say close B2 and B5 in #inbox (only his account can)
- Live's folder: his word, then the work folder's old `.env` and `data\`
  go (not deleted)
