"""The Problem class: what to solve, and the settings of its runs, read from the problem file.

The problem file is written in YAML. For now it holds:

    name: circle_packing
    description: |
      What the program must do, shown to the LLM in every prompt.
    entry_functions: [run_packing]         # the functions every program must define
    packages: [numpy==2.5.4]               # optional: what programs may import, exact versions
    llm:
      model: qwen3-coder:30b               # the model's name, as its server knows it
      api_base: http://localhost:11434/v1  # the server's OpenAI-compatible address
    evaluation:                            # optional
      stage_time_limit: 60                 # seconds each cascade stage may take
      thresholds: [0.5]                    # stage k + 1 runs if stage k's score reaches the k-th
    prompt:                                # optional
      max_feedback_chars: 2000             # feedback and errors are cut to this length
    sandbox:                               # optional: the limits of the Docker sandbox
      memory: 1g                           # memory, without swap (Docker's notation)
      cpus: 1                              # CPUs
      max_processes: 64                    # processes and threads

Every key is checked, and an unknown key is an error rather than silently ignored.
"""

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# An amount of memory in Docker's notation, such as "1g" or "512m"
MEMORY_PATTERN = re.compile(r"[0-9]+(\.[0-9]+)?[bkmg]?")
# A package with its exact version, such as "numpy==2.5.4": nothing else is accepted
PACKAGE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9.+!_-]*")


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

    # How long each cascade stage may take, in seconds, before its status is timeout
    stage_time_limit: float = 60.0
    # The score stage k must reach for stage k + 1 to run, one per stage after the first
    thresholds: tuple[float, ...] = ()


@dataclass(frozen=True)
class SandboxSettings:
    """The limits of the Docker sandbox's containers."""

    # Memory, without swap, in Docker's notation
    memory: str = "1g"
    # How many CPUs a container may use; numeric libraries get as many threads
    cpus: float = 1.0
    # How many processes and threads a container may run
    max_processes: int = 64


@dataclass(frozen=True)
class PromptSettings:
    """What the prompt shows."""

    # The longest feedback or error shown for one program, in characters
    max_feedback_chars: int = 2000


@dataclass(frozen=True)
class Problem:
    """A problem to solve, and every setting of its runs."""

    # A short name, used to name the run folders
    name: str
    # What the program must do, including the contract of its entry functions
    description: str
    # The LLM that writes the programs
    llm: LLMSettings
    # The packages programs may import besides the standard library, such as "numpy==2.5.4"
    packages: tuple[str, ...] = ()
    # The functions every program must define at its top level, such as ("run_packing",)
    entry_functions: tuple[str, ...] = ()
    # How programs are evaluated
    evaluation: EvaluationSettings = field(default_factory=EvaluationSettings)
    # The limits of the Docker sandbox
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)
    # What the prompt shows
    prompt: PromptSettings = field(default_factory=PromptSettings)

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
            required={"name", "description", "entry_functions", "llm"},
            optional={"packages", "evaluation", "sandbox", "prompt"},
        )
        llm = checked_section(top["llm"], "the llm section", required={"model", "api_base"})
        evaluation = checked_section(
            top.get("evaluation", {}),
            "the evaluation section",
            optional={"stage_time_limit", "thresholds"},
        )
        sandbox = checked_section(
            top.get("sandbox", {}),
            "the sandbox section",
            optional={"memory", "cpus", "max_processes"},
        )
        prompt = checked_section(
            top.get("prompt", {}), "the prompt section", optional={"max_feedback_chars"}
        )
        defaults = EvaluationSettings()
        sandbox_defaults = SandboxSettings()
        return cls(
            name=checked_text(top, "name", "the problem file"),
            description=checked_text(top, "description", "the problem file"),
            entry_functions=checked_entry_functions(top["entry_functions"]),
            llm=LLMSettings(
                model=checked_text(llm, "model", "the llm section"),
                api_base=checked_text(llm, "api_base", "the llm section"),
            ),
            packages=checked_packages(top.get("packages", [])),
            evaluation=EvaluationSettings(
                stage_time_limit=checked_positive_number(
                    evaluation,
                    "stage_time_limit",
                    "the evaluation section",
                    defaults.stage_time_limit,
                ),
                thresholds=checked_thresholds(evaluation.get("thresholds", [])),
            ),
            prompt=PromptSettings(
                max_feedback_chars=checked_count(
                    prompt,
                    "max_feedback_chars",
                    "the prompt section",
                    PromptSettings().max_feedback_chars,
                ),
            ),
            sandbox=SandboxSettings(
                memory=checked_memory(sandbox.get("memory", sandbox_defaults.memory)),
                cpus=checked_positive_number(
                    sandbox, "cpus", "the sandbox section", sandbox_defaults.cpus
                ),
                max_processes=checked_count(
                    sandbox, "max_processes", "the sandbox section", sandbox_defaults.max_processes
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


def checked_entry_functions(value: Any) -> tuple[str, ...]:
    """Return the entry functions' names: a list of one or more Python names."""
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(name, str) and name.isidentifier() for name in value)
    ):
        raise ProblemError(
            f"'entry_functions' must be a list of function names, such as [run_packing]; "
            f"got {value!r}"
        )
    return tuple(value)


def checked_thresholds(value: Any) -> tuple[float, ...]:
    """Return the cascade's thresholds: a list of finite numbers."""
    if not isinstance(value, list) or not all(
        isinstance(item, int | float) and not isinstance(item, bool) and math.isfinite(item)
        for item in value
    ):
        raise ProblemError(
            f"'thresholds' in the evaluation section must be a list of numbers, got {value!r}"
        )
    return tuple(float(item) for item in value)


def checked_count(section: dict[str, Any], key: str, where: str, default: int) -> int:
    """Return the value of a key that must hold a whole number of 1 or more, or the default."""
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProblemError(f"{key!r} in {where} must be a whole number of 1 or more, got {value!r}")
    return value


def checked_memory(value: Any) -> str:
    """Return an amount of memory written in Docker's notation, such as "1g" or "512m"."""
    if not isinstance(value, str) or not MEMORY_PATTERN.fullmatch(value):
        raise ProblemError(
            f"'memory' in the sandbox section must be like 1g or 512m, got {value!r}"
        )
    return value


def package_name(package: str) -> str:
    """Return a package's name without its version: "numpy==2.5.4" gives "numpy"."""
    return package.split("==", 1)[0]


def checked_packages(value: Any) -> tuple[str, ...]:
    """Return the package list if every entry is a name with an exact version.

    Only "name==version" is accepted: no version ranges, and no pip options, which
    could make pip install from anywhere.
    """
    if not isinstance(value, list):
        raise ProblemError("'packages' must be a list, such as [numpy==2.5.4]")
    names = set()
    for package in value:
        if not isinstance(package, str) or not PACKAGE_PATTERN.fullmatch(package):
            raise ProblemError(
                f"'packages' entries must be a name with an exact version, such as "
                f"numpy==2.5.4; got {package!r}"
            )
        if package_name(package).lower() in names:
            raise ProblemError(f"the package {package_name(package)!r} is listed twice")
        names.add(package_name(package).lower())
    return tuple(value)


def checked_text(section: dict[str, Any], key: str, where: str) -> str:
    """Return the value of a key that must hold some text."""
    value = section[key]
    if not isinstance(value, str) or not value.strip():
        raise ProblemError(f"{key!r} in {where} must be some text")
    return value
