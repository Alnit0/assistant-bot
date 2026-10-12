"""A test that hangs fails fast, with its name and where every thread was.

Without this a hang shows as a row of dots that stops, and nothing says which
test it was. Windows has no alarm signal, so a timer thread watches each test
and ends the whole run when one overstays: nothing else can stop a test that
is stuck in a loop or in a wait of its own."""
import faulthandler
import os
import sys
import threading

SECONDS = float(os.environ.get("TEST_TIMEOUT") or 60)  # the slowest test takes about two
EXIT_CODE = 70  # never 0: a run cut short must never look like one that passed


def watch(name: str, seconds: float = SECONDS, release=None) -> threading.Timer:
    """Start watching one test. Cancel the timer when the test is over.
    `release` is called first when a test overstays: pytest holds the output
    back while a test runs, and what is said here must get out."""

    def give_up() -> None:
        try:
            if release is not None:
                release()
        except Exception:
            pass
        sys.stderr.write(f"\n\nTIMEOUT: {name} ran for more than {seconds:g} seconds. The run is stopped here; where each thread was:\n")
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
        sys.stderr.flush()
        os._exit(EXIT_CODE)

    timer = threading.Timer(seconds, give_up)
    timer.daemon = True
    timer.start()
    return timer
