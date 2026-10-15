# Google Calendar setup

How the bot reads calendars through Google and adds events to a calendar
of its own. No key, id or link is in this file or anywhere committed:
they are in live's `.env` and next to it only.

## What Alex did (15 Oct)

1. Made a Google Cloud project and switched on the Google Calendar API
   for it.
2. Made a service account in that project and downloaded its key (a
   JSON file).
3. Made a new calendar in Google Calendar for the bot ("Bot") and shared
   it with the service account's address, with "Make changes to events".
4. Shared his own calendar with the service account, with "See all event
   details".
5. Sent the key and the Bot calendar's id. The key is now in live's
   `data\secrets\` (outside git, readable by his Windows user and the
   service only), and the upload was deleted.

## The settings (live's `.env`)

| Setting | What it is |
|---|---|
| `GOOGLE_SA_KEY_PATH` | Where the key file is |
| `CALENDAR_BOT_ID` | The Bot calendar's id: the only calendar ever written to |
| `CALENDAR_MAIN_ID` | His own calendar's id (kept, not read yet) |
| `CALENDAR_READ` | Which calendars to read, comma apart (below) |
| `CALENDAR_WRITE` | `true`: add, move and delete events in words, in the Bot calendar only |
| `CALENDAR_ICS_URL` | The secret iCal link, while his events come from it |

`CALENDAR_READ` lists each calendar as one of:

- `ics`: the iCal link in `CALENDAR_ICS_URL`
- `google:<calendar id>`: a calendar shared with the service account
- `google:<setting>`: the same, with the id in a setting of its own
  (`google:CALENDAR_MAIN_ID`, `google:CALENDAR_BOT_ID`)

Unset, it is `ics`. With `CALENDAR_WRITE` on, the Bot calendar is read
too, listed or not. Events from all of them are shown as one; the same
event in two calendars (the same title and times) is shown once.

Tonight (16 Oct): `CALENDAR_READ=ics,google:CALENDAR_BOT_ID`. His events
come from the link; the Bot calendar is read and written through Google.

## Adding another calendar later

1. In Google Calendar, open the calendar's settings, "Share with specific
   people", and add the service account's address (in the key file,
   `client_email`) with "See all event details".
2. Copy the calendar's id from "Integrate calendar" in the same page.
3. In live's `.env`, add it to `CALENDAR_READ` (as `google:<id>`, or put
   the id in a setting of its own and list `google:<setting>`).
4. Restart live once. The calendar's events are in the next read (every
   15 minutes and at start).

## Moving his own events from the iCal link to Google

Once the right calendar id is known (the Gmail calendar showed 1 event
against 5 that week from the link, so his events may be on another):

1. Check it: its events this week should match the link's.
2. Set `CALENDAR_READ=google:<that id>,google:CALENDAR_BOT_ID`.
3. Restart live once, and check the event count is the same as before.
4. Then remove `CALENDAR_ICS_URL` from live's `.env`, and reset the old
   secret iCal link in Google Calendar's settings, so the old one stops
   working.

## What the bot will never do

- Write to any calendar but the Bot calendar (checked on every write,
  in `tasks/calendar/google.py`, and tested).
- Change an event it did not add: it says so, and offers to add one.
- Send an event's name to Claude, or print, log or commit the key, an
  id or the link.
