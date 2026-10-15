import asyncio
import json
import logging
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path

from tasks.reading.rules import THEMES, Item

log = logging.getLogger("assistant")

# ---------------------------------------------------------------------------
# Where the daily read comes from: RSS and Atom feeds, the starter list in
# tasks/reading/feeds.json (not in code), and each chosen article's page,
# read down to its text. The one module that talks to the outside; tests
# replace `_get`. A failure raises: the caller keeps it quiet.
# ---------------------------------------------------------------------------
FEEDS = Path(__file__).with_name("feeds.json")
TIMEOUT = 10
MAX_BYTES = 3_000_000
AGENT = "assistant-bot daily read (personal use)"
ATOM = "{http://www.w3.org/2005/Atom}"


@dataclass(frozen=True)
class Source:
    name: str
    url: str
    theme: str


def _made_up() -> dict | None:
    """READING_SOURCE (the dev bot's replay only): made-up feeds and pages, read in place of the internet."""
    from core import config

    return json.loads(Path(config.READING_SOURCE).read_text(encoding="utf-8")) if config.READING_SOURCE else None


def starter() -> list[Source]:
    """The sources in feeds.json (or in the made-up file, for the replay)."""
    data = _made_up() or json.loads(FEEDS.read_text(encoding="utf-8"))
    return [Source(each["name"], each["url"], each["theme"]) for each in data["sources"] if each.get("theme") in THEMES]


def _get(url: str) -> bytes:
    made_up = _made_up()
    if made_up is not None:
        if url not in made_up["pages"]:
            raise OSError("not in the made-up pages")
        return made_up["pages"][url].encode("utf-8")
    request = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as answer:
        return answer.read(MAX_BYTES)


async def get(url: str) -> bytes:
    """One page or feed, off the event loop. Raises on any failure."""
    return await asyncio.to_thread(_get, url)


def _when(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        found = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            found = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return found if found.tzinfo else found.replace(tzinfo=timezone.utc)


def _closed_entries(raw: bytes) -> tuple[str, list]:
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
    for entry in (each for each in entries if each.tag == "item"):
        link, title = (entry.findtext("link") or "").strip(), (entry.findtext("title") or "").strip()
        found.append(Item(link, title, source.name, source.theme, _when(entry.findtext("pubDate"))))
    for entry in (each for each in entries if each.tag == f"{ATOM}entry"):
        links = entry.findall(f"{ATOM}link")
        link = next((each.get("href", "") for each in links if each.get("rel", "alternate") == "alternate"), links[0].get("href", "") if links else "")
        title = (entry.findtext(f"{ATOM}title") or "").strip()
        found.append(Item(link.strip(), title, source.name, source.theme, _when(entry.findtext(f"{ATOM}published") or entry.findtext(f"{ATOM}updated"))))
    if tag not in ("rss", f"{ATOM}feed", "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF") and not found:
        raise ValueError("not a feed")
    return [each for each in found if each.url.startswith("http") and each.title]


async def feed(source: Source) -> list[Item]:
    return parse_feed(await get(source.url), source)


class _Text(HTMLParser):
    """A page's readable text: what is in <article> (or <main>, or the body), without scripts,
    styles, navigation, headers, footers, forms or asides. Paragraphs kept apart."""

    SKIP = {"script", "style", "nav", "header", "footer", "form", "aside", "noscript", "svg", "button", "figure"}
    BLOCKS = {"p", "h1", "h2", "h3", "h4", "li", "pre", "blockquote", "br", "div", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skipping = 0
        self.parts: dict[str, list[str]] = {"article": [], "main": [], "body": []}
        self.inside = {"article": 0, "main": 0, "body": 0}

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skipping += 1
        if tag in self.inside:
            self.inside[tag] += 1
        if tag in self.BLOCKS:
            self._add("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        if tag in self.inside and self.inside[tag]:
            self.inside[tag] -= 1
        if tag in self.BLOCKS:
            self._add("\n")

    def handle_data(self, data):
        if not self.skipping:
            self._add(data)

    def _add(self, text):
        for name, depth in self.inside.items():
            if depth:
                self.parts[name].append(text)

    def text(self) -> str:
        for name in ("article", "main", "body"):
            joined = "".join(self.parts[name])
            lines = [" ".join(line.split()) for line in joined.splitlines()]
            found = "\n".join(line for line in lines if line)
            if len(found.split()) >= 150:
                return found
        return "\n".join(line for line in (" ".join(each.split()) for each in "".join(self.parts["body"]).splitlines()) if line)


def page_text(raw: bytes) -> str:
    reader = _Text()
    reader.feed(raw.decode("utf-8", errors="replace"))
    return reader.text()


async def article(url: str) -> str:
    """An article's readable text. Raises on a failure; may be short or a paywall (rules.readable says)."""
    return page_text(await get(url))
