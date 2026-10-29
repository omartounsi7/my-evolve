"""The Problem class: what to solve, and the settings of its runs, read from the problem file.

The problem file is written in YAML. For now it holds:

    name: circle_packing
    description: |
      What the program must do, shown to the LLM in every prompt.
    llm:
      model: qwen3-coder:30b               # the model's name, as its server knows it
      api_base: http://localhost:11434/v1  # the server's OpenAI-compatible address
    evaluation:                            # optional
      stage_time_limit: 60                 # seconds a program's evaluation may take

Every key is checked, and an unknown key is an error rather than silently ignored.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


class ProblemError(ValueError):
    """Raised when a problem file cannot be read or breaks a rule; the message says why."""


@dataclass(frozen=True)
class LLMSettings:
    """Which model writes the programs, and where to reach it."""

    # The model's name, as its server knows it
    model: str
    # The address of the server's OpenAI-compatible interface
    api_base: str


@dataclass(frozen=True)
class EvaluationSettings:
    """How programs are evaluated."""

    # How long a program's evaluation may take, in seconds, before its status is timeout
    stage_time_limit: float = 60.0


@dataclass(frozen=True)
class Problem:
    """A problem to solve, and every setting of its runs."""

    # A short name, used to name the run folders
    name: str
    # What the program must do, including the contract of its entry functions
    description: str
    # The LLM that writes the programs
    llm: LLMSettings
    # How programs are evaluated
    evaluation: EvaluationSettings = field(default_factory=EvaluationSettings)

    @classmethod
    def load(cls, path: Path) -> "Problem":
        """Read a problem file. Raises ProblemError, naming the file, if anything is wrong."""
        try:
            # safe_load reads plain data only (text, numbers, lists, mappings), never objects.
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise ProblemError(f"{path}: cannot be read: {error}") from error
        try:
            return cls.from_dict(data)
        except ProblemError as error:
            raise ProblemError(f"{path}: {error}") from error

    @classmethod
    def from_dict(cls, data: Any) -> "Problem":
        """Build a problem from the parsed content of a problem file, checking every value."""
        top = checked_section(
            data,
            "the problem file",
            required={"name", "description", "llm"},
            optional={"evaluation"},
        )
        llm = checked_section(top["llm"], "the llm section", required={"model", "api_base"})
        evaluation = checked_section(
            top.get("evaluation", {}), "the evaluation section", optional={"stage_time_limit"}
        )
        defaults = EvaluationSettings()
        return cls(
            name=checked_text(top, "name", "the problem file"),
            description=checked_text(top, "description", "the problem file"),
            llm=LLMSettings(
                model=checked_text(llm, "model", "the llm section"),
                api_base=checked_text(llm, "api_base", "the llm section"),
            ),
            evaluation=EvaluationSettings(
                stage_time_limit=checked_positive_number(
                    evaluation,
                    "stage_time_limit",
                    "the evaluation section",
                    defaults.stage_time_limit,
                ),
            ),
        )


def checked_section(
    section: Any,
    where: str,
    required: frozenset[str] | set[str] = frozenset(),
    optional: frozenset[str] | set[str] = frozenset(),
) -> dict[str, Any]:
    """Return a section of the file if it is a mapping with every required key, and no key
    that is neither required nor optional.

    where names the section in error messages, such as "the llm section".
    """
    if not isinstance(section, dict):
        raise ProblemError(f"{where} must be a mapping of keys to values")
    unknown = sorted(str(key) for key in section if key not in required | optional)
    if unknown:
        raise ProblemError(f"unknown key {unknown[0]!r} in {where}")
    missing = sorted(required - set(section))
    if missing:
        raise ProblemError(f"missing key {missing[0]!r} in {where}")
    return section


def checked_positive_number(section: dict[str, Any], key: str, where: str, default: float) -> float:
    """Return the value of a key that must hold a number above 0, or the default if it is absent."""
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int | float) or not value > 0:
        raise ProblemError(f"{key!r} in {where} must be a number above 0, got {value!r}")
    return float(value)


def checked_text(section: dict[str, Any], key: str, where: str) -> str:
    """Return the value of a key that must hold some text."""
    value = section[key]
    if not isinstance(value, str) or not value.strip():
        raise ProblemError(f"{key!r} in {where} must be some text")
    return value
