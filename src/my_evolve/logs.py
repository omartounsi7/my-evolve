"""Logging set-up (D52, D78): the console, and log.txt in the run folder.

Every module logs through its own logger, logging.getLogger(__name__), all under the
package's logger "my_evolve". The console shows the messages alone (one line per
iteration, the start and the end of the run), and the details only with --verbose;
log.txt gets everything, with the time, the level and the module.

No secret is ever logged: API keys are read only inside OpenAICompatibleLLM (D46).
"""

import logging
import sys
from pathlib import Path
from typing import TextIO

PACKAGE_LOGGER = "my_evolve"
FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

# Libraries that log every HTTP request at the INFO level: only their warnings matter.
CHATTY_LIBRARIES = ("httpx", "httpcore", "openai")

# Marks the handlers this module added, so that a second set-up replaces them.
OWN_HANDLER = "_my_evolve_handler"


class ConsoleFormatter(logging.Formatter):
    """Shows a message alone, with "Warning:" or "Error:" before the serious ones."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if record.levelno >= logging.ERROR:
            return f"Error: {message}"
        if record.levelno >= logging.WARNING:
            return f"Warning: {message}"
        return message


def setup_logging(folder: Path | None, verbose: bool, console: TextIO | None = None) -> None:
    """Send the package's messages to the console and, if folder is given, to folder/log.txt.

    console is where console lines go (by default standard output). Calling it again
    replaces the handlers of the previous call, so a second run in the same process
    does not log every line twice.
    """
    stop_logging()
    package_logger = logging.getLogger(PACKAGE_LOGGER)
    # The package's logger lets everything through; each handler chooses what it shows.
    package_logger.setLevel(logging.DEBUG)
    # The package's lines are shown by its own handlers only, never twice through the root's.
    package_logger.propagate = False

    console_handler = logging.StreamHandler(console if console is not None else sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(ConsoleFormatter("%(message)s"))
    add_own_handler(package_logger, console_handler)

    if folder is not None:
        file_handler = logging.FileHandler(folder / "log.txt", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        add_own_handler(package_logger, file_handler)

    for name in CHATTY_LIBRARIES:
        logging.getLogger(name).setLevel(logging.WARNING)


def add_own_handler(logger: logging.Logger, handler: logging.Handler) -> None:
    """Add a handler to a logger, marked as one of this module's."""
    setattr(handler, OWN_HANDLER, True)
    logger.addHandler(handler)


def stop_logging() -> None:
    """Remove and close the handlers setup_logging added (closing log.txt)."""
    package_logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(package_logger.handlers):
        if getattr(handler, OWN_HANDLER, False):
            package_logger.removeHandler(handler)
            handler.close()
