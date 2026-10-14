"""How the tests open a database (tests/fastdb.py, tests/conftest.py): fast, and with nothing changed in what
the bot's code sees. And, marked to run as on live, the real thing: a worker thread and a connection of its own."""
import asyncio
import sqlite3
import threading

import pytest

from core import database
from tests import fastdb


def _table(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS things (name TEXT)")
    conn.commit()


def _names():
    conn = database.connect()
    try:
        return [row[0] for row in conn.execute("SELECT name FROM things ORDER BY rowid")]
    finally:
        conn.close()


def test_work_that_was_not_committed_is_gone_when_the_connection_is_closed_as_with_a_real_one(db):
    conn = database.connect()
    _table(conn)
    conn.execute("INSERT INTO things VALUES ('kept')")
    conn.commit()
    conn.execute("INSERT INTO things VALUES ('never committed')")
    conn.close()
    assert _names() == ["kept"], "closing discards what was not committed"

    with pytest.raises(ZeroDivisionError):
        asyncio.run(database.run(lambda conn: (conn.execute("INSERT INTO things VALUES ('half done')"), 1 / 0)))
    assert _names() == ["kept"], "a piece of work that raised left nothing behind"
    asyncio.run(database.run(lambda conn: conn.execute("INSERT INTO things VALUES ('done')")))
    assert _names() == ["kept", "done"]


fast_only = pytest.mark.skipif(bool(__import__("os").environ.get("TESTS_AS_ON_LIVE")), reason="about the fast way itself: not in a run made as on live")


def test_what_a_caller_set_on_its_connection_does_not_follow_to_the_next_one(db):
    first = database.connect()
    _table(first)
    first.row_factory = sqlite3.Row
    first.isolation_level = None  # as the migrations do
    first.close()
    second = database.connect()
    try:
        assert second.row_factory is None and second.execute("SELECT 1").fetchone() == (1,)
        assert second.isolation_level == "", "its transactions are on again: work that is not committed can be rolled back"
        assert second.execute("PRAGMA foreign_keys").fetchone() == (1,), "the bot's own setting is there every time"
    finally:
        second.close()


@fast_only
def test_the_kept_connection_is_lent_to_one_user_at_a_time(db):
    first = database.connect()
    _table(first)
    first.execute("INSERT INTO things VALUES ('not committed yet')")
    second = database.connect()
    try:
        assert second is not first and isinstance(second, sqlite3.Connection), "a second one while the first is in use is a real one of its own"
        assert second.execute("SELECT COUNT(*) FROM things").fetchone() == (0,), "and it sees only what is committed, as on live"
    finally:
        second.close()
    first.commit()
    first.close()
    assert database.connect() is first, "given back, it is lent again: the file is opened once a test"
    first.close()
    assert _names() == ["not committed yet"]


@fast_only
def test_another_thread_gets_a_connection_of_its_own(db):
    mine = database.connect()
    _table(mine)
    mine.close()
    found = []

    def elsewhere():
        conn = database.connect()
        found.append((conn is mine, isinstance(conn, sqlite3.Connection), conn.execute("SELECT COUNT(*) FROM things").fetchone()))
        conn.close()

    thread = threading.Thread(target=elsewhere)
    thread.start()
    thread.join()
    assert found == [(False, True, (0,))]


def test_the_file_is_let_go_of_when_the_test_is_over():
    assert fastdb._kept == {}, "nothing is held open from the test before"


@fast_only
def test_blocking_work_is_done_in_the_test_s_own_thread_after_the_loop_has_had_its_turn(db):
    order = []

    async def other():
        order.append("the loop ran something else")

    async def both():
        waiting = asyncio.create_task(other())
        order.append(await database.run(lambda conn: threading.get_ident()))
        await waiting

    asyncio.run(both())
    assert order == ["the loop ran something else", threading.get_ident()], "handing work over still gives the loop its turn"


@pytest.mark.real_threads
@pytest.mark.real_connections
def test_as_on_live_database_work_runs_in_a_worker_thread_on_a_connection_opened_and_closed_for_it(db):
    seen = []

    def work(conn):
        seen.append((threading.get_ident(), type(conn)))
        conn.execute("CREATE TABLE things (name TEXT)")
        conn.execute("INSERT INTO things VALUES ('from a worker')")
        return conn

    conn = asyncio.run(database.run(work))
    (where, kind), = seen
    assert where != threading.get_ident() and kind is sqlite3.Connection, "off the event loop's thread, on a real connection"
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")  # closed when the work was done
    assert fastdb._kept == {} and asyncio.run(database.run(lambda conn: conn.execute("SELECT name FROM things").fetchall())) == [("from a worker",)]


@pytest.mark.real_threads
@pytest.mark.real_connections
def test_as_on_live_work_that_raises_in_its_thread_commits_nothing(db):
    asyncio.run(database.run(lambda conn: conn.execute("CREATE TABLE things (name TEXT)")))
    with pytest.raises(ZeroDivisionError):
        asyncio.run(database.run(lambda conn: (conn.execute("INSERT INTO things VALUES ('half done')"), 1 / 0)))
    assert asyncio.run(database.run(lambda conn: conn.execute("SELECT COUNT(*) FROM things").fetchone())) == (0,)
