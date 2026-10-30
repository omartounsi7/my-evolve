"""Draw the report of a run: its progress, and its best programs' outputs (D51, D79).

Usage:
    python scripts/report.py RUN_FOLDER

The drawings go into RUN_FOLDER/report/. The run folder is only read, so a run still in
progress can be reported on.
"""

import argparse
import io
import sys
from pathlib import Path

from my_evolve.evaluator import EvaluationFileError
from my_evolve.report import REPORT_FOLDER, ReportError, write_report


def main(arguments: list[str]) -> int:
    """Draw the report from the command line; return the exit code."""
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Draw the report of a my-evolve run.")
    parser.add_argument("run_folder", type=Path, help="the run folder, as run.py wrote it")
    parsed = parser.parse_args(arguments)
    if not parsed.run_folder.is_dir():
        parser.error(f"no such folder: {parsed.run_folder}")
    try:
        written = write_report(parsed.run_folder)
    except (ReportError, EvaluationFileError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(f"{len(written)} files written in {parsed.run_folder / REPORT_FOLDER}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
