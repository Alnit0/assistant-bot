"""Draft (16 Oct, 12:55): the daily read retuned to practical (Alex: the picks are very academic). Ratings of
difficulty and practicality for every candidate, a target the words can move, a TL;DR in plain English ending
"After reading, you will be able to …", a feed cut at the size cap read up to the cut, and the sources reviewed.
Apply from the repo root with no self-test running, then delete this file."""
import json
from pathlib import Path


def patch(path, pairs):
    p = Path(path)
    raw = p.read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    t = raw.replace("\r\n", "\n")
    for old, new in pairs:
        assert t.count(old) == 1, (path, old[:70], t.count(old))
        t = t.replace(old, new, 1)
    p.write_bytes((t.replace("\n", "\r\n") if crlf else t).encode("utf-8"))


# --- rules: the target, the ratings on a read, the TL;DR's last line ---------------------------------------------------
patch("tasks/reading/rules.py", [
    ('''HARDER, EASIER = "harder", "easier"''', '''HARDER, EASIER, PRACTICAL = "harder", "easier", "more_practical"
# Who it is for (Alex, 16 Oct: "very academic, maybe too high level"): a working web developer curious about AI.
# Every candidate is rated 1 (beginner) to 5 (research) for difficulty and 1 to 5 for practicality; the pick is
# from DIFFICULTY (moved one either way by "easier" or "harder") with practicality PRACTICAL_MIN or more (5 after
# "more practical"). Both ratings are kept with the read, so feedback can move the target later
DIFFICULTY = (2, 3)
PRACTICAL_MIN = 4
AFTER = "After reading, you will be able to"'''),
    ('''    vote: int = 0  # 1 thumbed up, -1 down, 0 neither
    saved: bool = False
''', '''    vote: int = 0  # 1 thumbed up, -1 down, 0 neither
    saved: bool = False
    difficulty: int | None = None  # Claude's rating when it was picked: 1 beginner to 5 research
    practicality: int | None = None  # 1 to 5
'''),
    ('''    level: int = 0  # -1 easier, 0 as it comes, 1 harder

    def as_dict(self) -> dict:
        return {"weights": self.weights, "more": self.more, "less": self.less, "level": self.level}''', '''    level: int = 0  # -1 easier, 0 as it comes, 1 harder
    practical: int = 0  # 1 after "more practical": practicality 5 only

    def as_dict(self) -> dict:
        return {"weights": self.weights, "more": self.more, "less": self.less, "level": self.level, "practical": self.practical}'''),
    ('''        return cls(weights, list(data.get("more") or []), list(data.get("less") or []), int(data.get("level") or 0))''',
     '''        return cls(weights, list(data.get("more") or []), list(data.get("less") or []), int(data.get("level") or 0), int(data.get("practical") or 0))'''),
    ('''    shift = {HARDER: 1, EASIER: -1}.get(level, 0)
    return replace(profile, more=more, less=less, level=max(-1, min(1, profile.level + shift)))''', '''    shift = {HARDER: 1, EASIER: -1}.get(level, 0)
    practical = 1 if level == PRACTICAL else profile.practical
    return replace(profile, more=more, less=less, level=max(-1, min(1, profile.level + shift)), practical=practical)


def target(profile: Profile) -> tuple[int, int, int]:
    """(lowest difficulty, highest, lowest practicality) the pick is made from."""
    low, high = DIFFICULTY
    return max(1, low + profile.level), min(5, high + profile.level), 5 if profile.practical else PRACTICAL_MIN


def in_target(rating: tuple[int, int] | None, profile: Profile) -> bool:
    low, high, practical = target(profile)
    return rating is not None and low <= rating[0] <= high and rating[1] >= practical'''),
    ('''    if profile.level:
        parts.append("prefer " + ("harder, more technical" if profile.level > 0 else "easier, more introductory") + " pieces")
    return "; ".join(parts) or "nothing more yet"''', '''    if profile.level:
        parts.append("prefer " + ("harder, more technical" if profile.level > 0 else "easier, more introductory") + " pieces")
    if profile.practical:
        parts.append("only the most practical pieces")
    return "; ".join(parts) or "nothing more yet"'''),
    ('''def tidy_tldr(text: str) -> str:
    """Claude's TL;DR as said: at most three lines, no em dashes, no headings."""
    lines = [re.sub(r"^[#>*\\-\\s]+", "", line).strip() for line in str(text or "").replace("—", ",").replace("–", "-").splitlines()]
    lines = [line for line in lines if line]
    return "\\n".join(lines[:3])[:420]''', '''def tidy_tldr(text: str) -> str:
    """Claude's TL;DR as said: at most three lines, then its "After reading, you will be able to …" line;
    no em dashes, no headings. A last line that is missing is not made up here."""
    lines = [re.sub(r"^[#>*\\-\\s]+", "", line).strip() for line in str(text or "").replace("—", ",").replace("–", "-").splitlines()]
    lines = [line for line in lines if line]
    after = next((line for line in reversed(lines) if line.startswith(AFTER)), "")
    body = [line for line in lines if line != after][:3]
    return "\\n".join(body)[:420] + (f"\\n{after[:160]}" if after and body else "")'''),
])

# --- the store: the ratings with each read -----------------------------------------------------------------------------
patch("tasks/reading/store.py", [
    ('''MIGRATIONS = [create_tables]''', '''def add_ratings(conn: sqlite3.Connection) -> None:
    """Claude's ratings of the read when it was picked: difficulty and practicality, 1 to 5."""
    conn.execute("ALTER TABLE reading_reads ADD COLUMN difficulty INTEGER")
    conn.execute("ALTER TABLE reading_reads ADD COLUMN practicality INTEGER")


MIGRATIONS = [create_tables, add_ratings]'''),
    ('''_READ = "url, title, source, theme, minutes, tldr, day, vote, saved"''', '''_READ = "url, title, source, theme, minutes, tldr, day, vote, saved, difficulty, practicality"'''),
    ('''    return Read(row[0], row[1], row[2], row[3], row[4], row[5], date.fromisoformat(row[6]), row[7], bool(row[8]))''',
     '''    return Read(row[0], row[1], row[2], row[3], row[4], row[5], date.fromisoformat(row[6]), row[7], bool(row[8]), row[9], row[10])'''),
    ('''        "INSERT INTO reading_reads (user_id, day, url, title, source, theme, minutes, tldr, shown_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, read.day.isoformat(), read.url, read.title, read.source, read.theme, read.minutes, read.tldr, now.isoformat()),''',
     '''        "INSERT INTO reading_reads (user_id, day, url, title, source, theme, minutes, tldr, shown_at, difficulty, practicality) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (user_id, read.day.isoformat(), read.url, read.title, read.source, read.theme, read.minutes, read.tldr, now.isoformat(), read.difficulty, read.practicality),'''),
])

# --- the pick ----------------------------------------------------------------------------------------------------------
patch("tasks/reading/pick.py", [
    ('''SYSTEM = (
    "You choose one article for a person's daily read and write its TL;DR. The read is for continuing education: "
    "keeping up with using AI, programming, and the significant tech news.\\n"
    "- Prefer explainers, tutorials and well-argued deep dives. Avoid hot takes, listicles, rumours and thin news "
    "rewrites; choose them only if nothing else is there.\\n"
    "- Prefer the day's theme, and what the person said they want more or less of.\\n"
    "- The TL;DR is 2 or 3 short lines, each a sentence of at most 20 words on a line of its own, written only from the article's text given here: what it explains and why "
    "it is worth the time. Make the person want to read it, but never promise what the article does not deliver, "
    "never add facts that are not in the text, and never use clickbait. Plain UK English, no em dashes, no headings.\\n"
    "- Call the pick tool with the article's number and the TL;DR."
)''', '''SYSTEM = (
    "You choose one article for a person's daily read and write its TL;DR. The person is a working web developer "
    "curious about AI, not a researcher: the read is practical and hands-on, about using AI, programming, and the "
    "significant tech news.\\n"
    "- Prefer how-tos, tool tips, worked examples, \\"I built X with Y\\" write-ups, and plain-English explainers of "
    "significant news. Avoid research papers, maths-heavy or theory-only pieces, and anything without a practical "
    "takeaway; avoid hot takes, listicles, rumours and thin news rewrites too.\\n"
    "- Rate every article: difficulty from 1 (beginner) to 5 (research), and practicality from 1 (nothing to use) to 5 "
    "(something to try today). Choose only from those in the range the message gives.\\n"
    "- Prefer the day's theme, and what the person said they want more or less of.\\n"
    "- The TL;DR is 2 or 3 short lines, each a sentence of at most 20 words on a line of its own, then one last line "
    "that starts \\"After reading, you will be able to\\". Plain English with no jargon, written only from the article's "
    "text given here: what it shows and why it is worth the time. Never promise what the article does not deliver, "
    "never add facts that are not in the text, and never use clickbait. UK English, no em dashes, no headings.\\n"
    "- Call the pick tool with every article's ratings, the article's number and the TL;DR."
)'''),
    ('''                "choice": {"type": "integer", "description": f"The chosen article's number, 1 to {count}."},
                "tldr": {"type": "string", "description": "2 or 3 short lines, one sentence each, separated by line breaks, from the article's text only."},
            },
            "required": ["choice", "tldr"],''', '''                "ratings": {
                    "type": "array",
                    "description": "Every article's ratings, one each.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "number": {"type": "integer"},
                            "difficulty": {"type": "integer", "description": "1 beginner to 5 research."},
                            "practicality": {"type": "integer", "description": "1 nothing to use to 5 something to try today."},
                        },
                        "required": ["number", "difficulty", "practicality"],
                    },
                },
                "choice": {"type": "integer", "description": f"The chosen article's number, 1 to {count}."},
                "tldr": {"type": "string", "description": "2 or 3 short lines, one sentence each, separated by line breaks, from the article's text only, then a line starting \\"After reading, you will be able to\\"."},
            },
            "required": ["ratings", "choice", "tldr"],'''),
    ('''def user_turn(found: list[Candidate], theme: str, profile: Profile, kind: str = "") -> str:
    parts = [f"Today's theme: {LABELS[theme]} ({ABOUT[theme]}).", f"What the person wants: {rules.guidance(profile)}."]''', '''def user_turn(found: list[Candidate], theme: str, profile: Profile, kind: str = "", only: list[int] | None = None) -> str:
    low, high, practical = rules.target(profile)
    parts = [
        f"Today's theme: {LABELS[theme]} ({ABOUT[theme]}).",
        f"What the person wants: {rules.guidance(profile)}.",
        f"Choose from difficulty {low} to {high} with practicality {practical} or more.",
    ]
    if only:
        parts.append(f"Of these, only {', '.join(str(each) for each in only)} are in that range: choose one of them.")'''),
    ('''def checked(raw, found: list[Candidate]) -> tuple[Candidate, str] | None:
    """The chosen candidate and its TL;DR, or None for anything that can't be used. Pure."""
    if not isinstance(raw, dict):
        return None
    choice = raw.get("choice")
    if not isinstance(choice, int) or not 1 <= choice <= len(found):
        return None
    tldr = rules.tidy_tldr(raw.get("tldr"))
    if not tldr:
        return None
    return found[choice - 1], tldr''', '''def ratings(raw, count: int) -> dict[int, tuple[int, int]]:
    """{article number: (difficulty, practicality)} for the ratings that can be used, each 1 to 5. Pure."""
    found = {}
    for each in (raw or {}).get("ratings") or [] if isinstance(raw, dict) else []:
        if not isinstance(each, dict):
            continue
        number, difficulty, practicality = each.get("number"), each.get("difficulty"), each.get("practicality")
        if all(isinstance(value, int) for value in (number, difficulty, practicality)) and 1 <= number <= count and 1 <= difficulty <= 5 and 1 <= practicality <= 5:
            found[number] = (difficulty, practicality)
    return found


def checked(raw, found: list[Candidate]) -> tuple[Candidate, str, tuple[int, int] | None] | None:
    """The chosen candidate, its TL;DR and its ratings, or None for anything that can't be used. Pure."""
    if not isinstance(raw, dict):
        return None
    choice = raw.get("choice")
    if not isinstance(choice, int) or not 1 <= choice <= len(found):
        return None
    tldr = rules.tidy_tldr(raw.get("tldr"))
    if not tldr:
        return None
    return found[choice - 1], tldr, ratings(raw, len(found)).get(choice)'''),
    ('''async def choose(found: list[Candidate], theme: str, profile: Profile, kind: str = "") -> tuple[Candidate, str] | None:
    """One request: the article to show and its TL;DR, or None."""
    if not found:
        return None
    called = await llm.call_tool(
        [{"type": "text", "text": SYSTEM, "cache_control": llm.CACHED}],
        user_turn(found, theme, profile, kind),
        [tool(len(found))],
        choice={"type": "tool", "name": TOOL},
        purpose=PURPOSE,
        task=rules.TASK,
        max_tokens=MAX_TOKENS,
    )
    picked = checked(called[1] if called else None, found)
    if picked is None:
        log.warning("Daily read: the pick came back unusable (%s)", "no tool call" if not called else "out of range or empty")
    return picked''', '''async def _ask(found: list[Candidate], theme: str, profile: Profile, kind: str, only: list[int] | None = None):
    called = await llm.call_tool(
        [{"type": "text", "text": SYSTEM, "cache_control": llm.CACHED}],
        user_turn(found, theme, profile, kind, only),
        [tool(len(found))],
        choice={"type": "tool", "name": TOOL},
        purpose=PURPOSE,
        task=rules.TASK,
        max_tokens=MAX_TOKENS,
    )
    return called[1] if called else None


async def choose(found: list[Candidate], theme: str, profile: Profile, kind: str = "") -> tuple[Candidate, str, tuple[int, int] | None] | None:
    """The article to show, its TL;DR and its ratings, or None. One request; a second only when the one
    chosen is out of the target while others are in it (they are named, and the choice is from them)."""
    if not found:
        return None
    raw = await _ask(found, theme, profile, kind)
    picked = checked(raw, found)
    if picked is None:
        log.warning("Daily read: the pick came back unusable (%s)", "no tool call" if raw is None else "out of range or empty")
        return None
    rated = ratings(raw, len(found))
    fitting = sorted(number for number, rating in rated.items() if rules.in_target(rating, profile))
    if rated and not rules.in_target(picked[2], profile) and fitting:
        again = checked(await _ask(found, theme, profile, kind, fitting), found)
        if again is not None and rules.in_target(again[2] or rated.get(found.index(again[0]) + 1), profile):
            picked = (again[0], again[1], again[2] or rated.get(found.index(again[0]) + 1))
        else:
            log.info("Daily read: the second pick was out of the target too; the first is kept")
    elif rated and not fitting:
        log.info("Daily read: nothing today was in the target; the closest was picked")
    if not picked[1].splitlines()[-1].startswith(rules.AFTER):
        log.info("Daily read: the TL;DR came without its After reading line")
    return picked'''),
])

# --- the read shown keeps its ratings ------------------------------------------------------------------------------------
patch("tasks/reading/plain.py", [
    ('''async def _show(user_id: int, day: date, chosen: Candidate, tldr: str) -> Read:
    read = Read(chosen.item.url, chosen.item.title, chosen.item.source, chosen.item.theme, chosen.minutes, tldr, day)''',
     '''async def _show(user_id: int, day: date, chosen: Candidate, tldr: str, rating: tuple[int, int] | None = None) -> Read:
    read = Read(chosen.item.url, chosen.item.title, chosen.item.source, chosen.item.theme, chosen.minutes, tldr, day,
                difficulty=rating[0] if rating else None, practicality=rating[1] if rating else None)'''),
    ('''"more_topic agents, \\"harder\\" or \\"easier\\" -> level.",''', '''"more_topic agents, \\"harder\\", \\"easier\\" or \\"more practical\\" -> level.",'''),
    ('''                Field("level", "harder or easier.", choices=(rules.HARDER, rules.EASIER)),''',
     '''                Field("level", "harder, easier, or more_practical (\\"more practical\\", \\"more hands-on\\").", choices=(rules.HARDER, rules.EASIER, rules.PRACTICAL)),'''),
])

# --- a feed bigger than the cap: its entries up to the cut ----------------------------------------------------------------
patch("tasks/reading/sources.py", [
    ('''def parse_feed(raw: bytes, source: Source) -> list[Item]:
    """The items of an RSS or Atom feed: link, title, when. Raises on what is not a feed."""
    root = ET.fromstring(raw)
    found = []
    for entry in root.iter("item"):''', '''def _closed_entries(raw: bytes) -> tuple[str, list]:
    """A feed cut at MAX_BYTES (16 Oct: two full-text feeds were 3.9 and 6.6 MB): its root's tag and every
    entry that closed before the cut. Feeds put the newest first, so nothing new is lost."""
    parser = ET.XMLPullParser(events=("start", "end"))
    root, entries = "", []
    try:
        for at in range(0, len(raw), 65536):
            parser.feed(raw[at:at + 65536])
            for event, element in parser.read_events():
                if event == "start" and not root:
                    root = element.tag
                elif event == "end" and element.tag in ("item", f"{ATOM}entry"):
                    entries.append(element)
    except ET.ParseError:
        pass
    return root, entries


def parse_feed(raw: bytes, source: Source) -> list[Item]:
    """The items of an RSS or Atom feed: link, title, when. Raises on what is not a feed. One cut at the
    size cap is read up to the cut."""
    try:
        tree = ET.fromstring(raw)
        tag, entries = tree.tag, [*tree.iter("item"), *tree.iter(f"{ATOM}entry")]
    except ET.ParseError:
        if len(raw) < MAX_BYTES:
            raise
        tag, entries = _closed_entries(raw)
    found = []
    for entry in (each for each in entries if each.tag == "item"):'''),
    ('''    for entry in root.iter(f"{ATOM}entry"):''', '''    for entry in (each for each in entries if each.tag == f"{ATOM}entry"):'''),
    ('''    if root.tag not in ("rss", f"{ATOM}feed", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF") and not found:''',
     '''    if tag not in ("rss", f"{ATOM}feed", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF") and not found:'''),
])

# --- the sources: practical ones in, academic ones out (each checked 16 Oct) --------------------------------------------
p = Path("tasks/reading/feeds.json")
feeds = json.loads(p.read_text(encoding="utf-8"))
dropped = {"Latent Space", "Hugging Face blog", "Eugene Yan", "Dan Luu"}
kept = [each for each in feeds["sources"] if each["name"] not in dropped]
added = [
    {"name": "Addy Osmani", "url": "https://addyosmani.com/rss.xml", "theme": "ai"},
    {"name": "GitHub blog", "url": "https://github.blog/feed/", "theme": "ai"},
    {"name": "Vercel blog", "url": "https://vercel.com/atom", "theme": "ai"},
    {"name": "Kent C. Dodds", "url": "https://kentcdodds.com/blog/rss.xml", "theme": "programming"},
    {"name": "Frontend Masters blog", "url": "https://frontendmasters.com/blog/feed/", "theme": "programming"},
]
feeds["about"] = ("The daily read's starter sources (tasks/reading): practical, for a working web developer curious about AI. "
                  "Reviewed 16 Oct 2026: the academic and research ones went, practical ones came in, each checked to work. "
                  "Alex adds or removes one in words; those changes are kept in the database, on top of this list.")
feeds["sources"] = kept + added
p.write_bytes((json.dumps(feeds, ensure_ascii=False, indent=2) + "\n").replace("\n", "\r\n").encode("utf-8"))
print("ok")
