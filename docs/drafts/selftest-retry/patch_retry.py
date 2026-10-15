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


patch("selftest/harness.py", [
    ('''PASS, FAIL, ERROR, SKIP = "pass", "fail", "error", "skip"
''', '''PASS, FAIL, ERROR, SKIP = "pass", "fail", "error", "skip"
# A step that failed twice while Discord answered with a server error (5xx) or a rate limit: not the
# bot's fault. No bug is filed and it is not counted as failed; the run's summary says it
DISCORD = "discord"
RETRY_WAIT = 10.0  # seconds before a step Discord got in the way of is run once more
_TROUBLE = re.compile(r"\\b(429 Too Many Requests|5\\d\\d (Service Unavailable|Bad Gateway|Internal Server Error|Gateway Timeout)|DiscordServerError|being rate limited)")
'''),
    ('''class Fail(Exception):
    """A step saw something other than what it expected."""
''', '''class Fail(Exception):
    """A step saw something other than what it expected."""


def discord_trouble(record: logging.LogRecord) -> str:
    """What Discord did wrong, if this log line says it answered with a server error or a rate
    limit (from the bot's own code, discord.py's, or a step's): "" for anything else."""
    if record.exc_info and record.exc_info[1] is not None:
        error = record.exc_info[1]
        status = getattr(error, "status", None)
        if isinstance(error, discord.DiscordServerError) or (isinstance(error, discord.HTTPException) and (status == 429 or (status or 0) >= 500)):
            return f"{status or 'a server error'}"
    found = _TROUBLE.search(record.getMessage())
    return found.group(1) if found else ""


class _Watch(logging.Handler):
    """Counts the times Discord got in the way while a step runs."""

    def __init__(self):
        super().__init__(logging.DEBUG)
        self.seen: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            said = discord_trouble(record)
        except Exception:
            return
        if said:
            self.seen.append(said)


class Attempt:
    """One go at a step: `async with attempt:` runs its body and keeps what happened."""

    def __init__(self, harness: "Harness", record: dict):
        self.harness, self.record = harness, record
        self.trouble: list[str] = []
        self._watch = _Watch()

    async def __aenter__(self) -> dict:
        self.harness._record = self.record
        logging.getLogger().addHandler(self._watch)
        return self.record

    async def __aexit__(self, kind, error, trace) -> bool:
        logging.getLogger().removeHandler(self._watch)
        self.trouble = list(self._watch.seen)
        if error is None:
            return False
        if isinstance(error, Fail):
            self.record["status"], self.record["saw"] = FAIL, str(error)
            return True
        if isinstance(error, Exception):  # the step itself broke: say where
            where = traceback.extract_tb(error.__traceback__)[-1]
            self.record["status"] = ERROR
            self.record["saw"] = f"{error!r} at {Path(where.filename).name}:{where.lineno}"
            said = discord_trouble(logging.LogRecord("step", logging.ERROR, "", 0, "", (), (kind, error, trace)))
            if said:
                self.trouble.append(said)
            log.exception("Self-test step %s broke", self.record["key"], exc_info=(kind, error, trace))
            return True
        return False
'''),
    ('''    @asynccontextmanager
    async def step(self, key: str, title: str, expect: str, source: str = ""):
        record = {"phase": self.phase, "key": key, "title": title, "expect": expect, "source": source, "status": PASS, "saw": "", "claude": "", "odd": "", "seconds": 0}
        self._record = record
        began = stopwatch.monotonic()
        try:
            yield record
        except Fail as failed:
            record["status"], record["saw"] = FAIL, str(failed)
        except Exception as error:  # the step itself broke: say where
            where = traceback.extract_tb(error.__traceback__)[-1]
            record["status"] = ERROR
            record["saw"] = f"{error!r} at {Path(where.filename).name}:{where.lineno}"
            log.exception("Self-test step %s broke", key)
        finally:
            record["seconds"] = round(stopwatch.monotonic() - began, 1)
            self._record = None
            self.results.append(record)
            self.save()
            self.tell_progress()
            print(f"[{record['status']:5}] {key} {title}" + (f" :: {record['saw'][:200]}" if record["status"] != PASS else ""), flush=True)''',
     '''    async def step(self, key: str, title: str, expect: str, source: str = ""):
        """`async for attempt in h.step(...): async with attempt: ...`: the body is one go at the step.
        One that fails while Discord answers with a server error or a rate limit is run once more
        after RETRY_WAIT; failing so again, it is DISCORD (Discord unavailable), not a bot fault."""
        began = stopwatch.monotonic()
        record: dict = {}
        for go in (1, 2):
            record = {"phase": self.phase, "key": key, "title": title, "expect": expect, "source": source, "status": PASS, "saw": "", "claude": "", "odd": "", "seconds": 0}
            attempt = Attempt(self, record)
            yield attempt
            self._record = None
            if record["status"] in (FAIL, ERROR) and attempt.trouble:
                said = ", ".join(sorted(set(attempt.trouble)))
                if go == 1:
                    print(f"[retry] {key} {title} :: Discord answered {said}: once more in {RETRY_WAIT:.0f} s", flush=True)
                    await asyncio.sleep(RETRY_WAIT)
                    continue
                record["status"], record["saw"] = DISCORD, f"Discord unavailable ({said}), twice: {record['saw']}"
            break
        record["seconds"] = round(stopwatch.monotonic() - began, 1)
        self.results.append(record)
        self.save()
        self.tell_progress()
        print(f"[{record['status'][:5]:5}] {key} {title}" + (f" :: {record['saw'][:200]}" if record["status"] != PASS else ""), flush=True)'''),
])

patch("selftest/report.py", [
    ('''MARK = {"pass": "✅ pass", "fail": "❌ fail", "error": "💥 broke", "skip": "⏭️ skipped"}''',
     '''MARK = {"pass": "✅ pass", "fail": "❌ fail", "error": "💥 broke", "skip": "⏭️ skipped", "discord": "📡 Discord unavailable"}'''),
    ('''        f"**Result:** {counts['pass']} passed, {counts['fail']} failed, {counts['error']} broke, {counts['skip']} skipped, of {len(results)} steps",''',
     '''        f"**Result:** {counts['pass']} passed, {counts['fail']} failed, {counts['error']} broke, {counts['skip']} skipped"
        + (f", {counts['discord']} Discord unavailable (no bug: Discord answered with a server error or a rate limit, twice)" if counts.get("discord") else "")
        + f", of {len(results)} steps",'''),
])

patch("selftest/__main__.py", [
    ('''    failed = {name for name, _, found in phases if found.get("exit") != 0 or any(each["status"] in ("fail", "error") for each in found["results"])}''',
     '''    # A step Discord got in the way of has not passed either: its stage is run again next time
    failed = {name for name, _, found in phases if found.get("exit") != 0 or any(each["status"] in ("fail", "error", "discord") for each in found["results"])}'''),
    ('''    print(f"--- {len(results)} steps, {len(bad)} failed{crashed_text(crashed)}, US${spent:.4f} spent. Report: {path}")''',
     '''    print(f"--- {len(results)} steps, {len(bad)} failed{unavailable_text(results)}{crashed_text(crashed)}, US${spent:.4f} spent. Report: {path}")'''),
    ('''def crashed_text(crashed) -> str:''', '''def unavailable_text(results) -> str:
    """The run summary's note of the steps Discord got in the way of, twice: not failures, no bug."""
    keys = [each["key"] for each in results if each["status"] == "discord"]
    return f" ({len(keys)} Discord unavailable, not counted: {' '.join(keys)})" if keys else ""


def crashed_text(crashed) -> str:'''),
])
print("ok")
