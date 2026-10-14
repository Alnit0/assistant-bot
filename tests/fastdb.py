"""A test's database, opened fast (tests/conftest.py puts `connect` in place of the bot's own for every test).

Three things made the suite slow on Windows, each measured on 2026-10-14: waiting for the disk after a
write, a journal file made and deleted for every write, and, the largest, closing the database file after
each piece of work. None of them is what a test is about. Everything the bot's code does with a connection
is unchanged: it opens one, uses it, commits or not, and closes it."""
import threading

from core import database

# The bot's own way of opening a connection, kept from before any test replaces it
_connect = database.connect


def opened():
    """A real connection that doesn't wait for the disk after every write: a test's
    database is thrown away, so nothing is lost if the machine stops."""
    conn = _connect()
    conn.execute("PRAGMA synchronous = OFF")
    # Nor is a journal file made and deleted beside the database for every write: it is kept in
    # memory. On Windows that file's making and unlinking was most of what a write cost
    conn.execute("PRAGMA journal_mode = MEMORY")
    return conn


class _Kept:
    """One real connection to a test's database, handed out again each time the code opens one.

    The bot opens a connection for every piece of database work and closes it after. On Windows
    closing a file that was written to costs about 1.6 ms, some 25,000 times a run (measured
    2026-10-14: the same write on a connection left open is 0.08 ms). So the file stays open
    for the length of the test, and where the code closes its connection, what a close does to
    the data is done instead: work that was not committed is rolled back, and what the caller
    set on the connection is put back as it was.

    It is only ever lent to one user at a time. Code that opens a second connection while the
    first is still in use gets a real one of its own, as does another thread, so two
    connections never share a transaction here that would not share one on live."""

    def __init__(self, real):
        # What a caller may set on a connection, as a newly opened one has it
        fresh = {name: getattr(real, name) for name in ("row_factory", "text_factory", "isolation_level")}
        self.__dict__.update(_real=real, _lent=False, _thread=threading.get_ident(), _fresh=fresh)

    def __getattr__(self, name):
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        if name in self.__dict__:
            self.__dict__[name] = value
        else:
            setattr(self._real, name, value)

    def __enter__(self):
        self._real.__enter__()
        return self

    def __exit__(self, *raised):
        return self._real.__exit__(*raised)

    def close(self):
        self._real.rollback()
        # The next user gets it as a newly opened one is. (The migrations turn its own
        # transactions off, for one: left so, nothing after them would ever be rolled back)
        for name, value in self._fresh.items():
            if getattr(self._real, name) != value:
                setattr(self._real, name, value)
        self._lent = False

    def really_close(self):
        self._real.close()


_kept: dict[str, _Kept] = {}  # the connection kept open for each database a test has used


def connect():
    """What the code gets when it opens a connection in a test: the one kept open for that
    database (`_Kept`), or a real one of its own while that is in use."""
    where = str(database.DB_PATH)
    kept = _kept.get(where)
    if kept is None:
        kept = _kept[where] = _Kept(opened())
    elif kept._lent or kept._thread != threading.get_ident():
        return opened()
    kept._lent = True
    return kept


def close_kept() -> None:
    for kept in _kept.values():
        kept.really_close()
    _kept.clear()
