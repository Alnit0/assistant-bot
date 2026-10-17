# The gym's spreadsheet mirror: setting it up

With the mirror on, every set you log (by the Log button, in words, or a
whole session described) is also written as a row of a Google Sheet, in
your logbook's own columns: Date, Week, Day, Exercise, Sets, Reps, Reps
Achieved, Weight, Objective, Notes. The bot's own record stays its
database; the sheet is a copy you can read and keep. It is off until you
do the steps below (`GYM_SHEET=false`).

It uses the same Google service account as the calendar
(`docs/GOOGLE-SETUP.md`): nothing new to make in Google Cloud, except
turning on the Sheets API.

## Steps for Alex

1. **Make the sheet.** In Google Sheets, a new spreadsheet (or a copy of
   your logbook). The first tab is the one written to. Put your column
   headings in row 1 if you like: rows are appended under what is there.
2. **Share it with the service account as an editor.** Share → add the
   service account's address (it is `client_email` in the key file named
   by `GOOGLE_SA_KEY_PATH`, the same address the Bot calendar is shared
   with) → Editor. Untick "Notify people".
3. **Turn on the Sheets API** for the service account's Google Cloud
   project: APIs & Services → Library → Google Sheets API → Enable.
4. **Give Claude Code the sheet's ID.** It is the long part of the
   sheet's link between `/d/` and `/edit`
   (`https://docs.google.com/spreadsheets/d/<the ID>/edit`). Paste it in
   a session; Claude Code puts it in live's `.env` as `GYM_SHEET_ID`
   with `GYM_SHEET=true`, and the mirror starts at the next restart.

## What to expect

- A row a set, written as it is logged; a set put right or undone is
  not rewritten in the sheet (the bot's own record has it right).
- A write that fails (the sheet unshared, the API off) is logged and
  nothing else: logging in the bot carries on as before.
- No id or key is ever printed or logged.
