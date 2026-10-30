"""Logging set-up (D52, D78): the console, and log.txt in the run folder.

Every module logs through its own logger (logging.getLogger(__name__)), under the
package's logger, "my_evolve". The console shows the messages alone: one line per
iteration, the start and the end of the run; with verbose, the details too (the
parents drawn, the checks, the timings). log.txt gets everything, with the time, the
level and the module. No secret is ever logged: API keys are only read inside
OpenAICompatibleLLM.
"""

import logging
import sys
from pathlib import Path

# The package's logger, which every module's logger belongs to
PACKAGE_LOGGER = "my_evolve"
# The log file of a run folder
LOG_FILE = "log.txt"


def setup_logging(folder: Path, verbose: bool) -> None:
    """Send the package's messages to the console and to log.txt in folder (created if needed).

    Calling it again replaces the handlers of the previous call.
    """
    logger = logging.getLogger(PACKAGE_LOGGER)
    stop_logging()
    # The package's logger lets everything through; each handler chooses what it shows.
    logger.setLevel(logging.DEBUG)
    # Its messages go to these handlers only, not to the root logger's.
    logger.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    folder.mkdir(parents=True, exist_ok=True)
    log_file = logging.FileHandler(folder / LOG_FILE, encoding="utf-8")
    log_file.setLevel(logging.DEBUG)
    log_file.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(log_file)


def stop_logging() -> None:
    """Remove and close the handlers setup_logging added, so that log.txt is closed."""
    logger = logging.getLogger(PACKAGE_LOGGER)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
