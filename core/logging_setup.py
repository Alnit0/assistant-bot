import logging
from logging.handlers import RotatingFileHandler

from core.config import LOG_DIR


def setup_logging() -> None:
    """Send logs to the terminal and to a rotating file in logs/."""
    log_format = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)

    file_handler = RotatingFileHandler(
        LOG_DIR / "bot.log",
        maxBytes=1_000_000,  # roughly 1MB per file
        backupCount=5,  # keep the 5 most recent files
        encoding="utf-8",
    )
    file_handler.setFormatter(log_format)

    logging.basicConfig(level=logging.INFO, handlers=[console_handler, file_handler])
