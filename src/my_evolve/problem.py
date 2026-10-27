"""The Problem class: a problem and every setting of its runs, read from the problem file.

The problem file is YAML (D43, D44). It is read as plain data, loaded into the
dataclasses below, and every value is checked: a key the program does not know is
an error, at any depth, so a misspelt setting can never be silently ignored.

Sections read so far (D72): the top level, evaluation, sandbox, prompt, parents
and llm. Other sections come with the features that use them.
"""

import hashlib
import json
import keyword
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from my_evolve.llm import is_reasoning_model

# Defaults of the top level and of each section (D72).
DEFAULT_SNAPSHOT_EVERY = 10
DEFAULT_MAX_ERRORS_IN_A_ROW = 3
DEFAULT_STAGE_TIME_LIMIT = 60.0
DEFAULT_MEMORY = "1g"
DEFAULT_CPUS = 1.0
DEFAULT_MAX_PROCESSES = 64
DEFAULT_MAX_FEEDBACK_CHARS = 2000
DEFAULT_PARENT_STRATEGY = "weighted"
DEFAULT_LAMBDA = 1.0
DEFAULT_WEIGHT = 1.0
DEFAULT_MAX_TOKENS = 16384
DEFAULT_TIMEOUT = 300.0
DEFAULT_RETRIES = 2
DEFAULT_MAX_FAILURES_IN_A_ROW = 3

# The parent strategies known so far (D19).
PARENT_STRATEGIES = ("weighted",)

# A problem's name becomes part of its run folder's name, so only safe characters.
NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]+")
# A package with its exact version, such as "numpy==2.5.4" (D71).
PACKAGE_PATTERN = re.compile(
    r"(?P<name>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)==[A-Za-z0-9][A-Za-z0-9.+!_-]*"
)
# A memory size as Docker accepts it: a whole number and a unit, such as "1g" or "512m".
MEMORY_PATTERN = re.compile(r"[1-9][0-9]*[kmgKMG]")
# An API key written as the name of the environment variable holding it (D46).
KEY_VARIABLE_PATTERN = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")

# The settings of a model that may be shared by every model of the llm section.
SHARED_MODEL_KEYS = (
    "api_base",
    "api_key",
    "max_tokens",
    "temperature",
    "reasoning_effort",
    "reasoning",
    "timeout",
    "retries",
    "price_input",
    "price_output",
)


class ProblemError(ValueError):
    """A problem file that cannot be used; the message says where and why."""


# ----------------------------------------------------------------------------------
# Reading YAML
# ----------------------------------------------------------------------------------


class UniqueKeyLoader(yaml.SafeLoader):
    """PyYAML's safe loader (plain data only), refusing a mapping that repeats a key.

    The plain loader keeps the last value of a repeated key without a word, which
    would silently ignore a setting.
    """


def construct_unique_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode) -> dict[Any, Any]:
    """Build a mapping, raising ProblemError if one of its keys appears twice."""
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node)
        try:
            repeated = key in seen
        except TypeError:
            # A key that is not a plain value: the base constructor reports it.
            continue
        if repeated:
            line = key_node.start_mark.line + 1
            raise ProblemError(f"line {line}: the key {key!r} appears twice")
        seen.add(key)
    return loader.construct_mapping(node)


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_unique_mapping
)


# ----------------------------------------------------------------------------------
# Checking values
# ----------------------------------------------------------------------------------


def describe(value: Any) -> str:
    """Return a short description of a wrong value for an error message."""
    if isinstance(value, dict):
        return "a mapping"
    if isinstance(value, list):
        return "a list"
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def as_integer(value: Any, where: str, minimum: int) -> int:
    """Return value if it is a whole number of at least minimum; a boolean is not one."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProblemError(f"{where}: must be a whole number, got {describe(value)}")
    if value < minimum:
        raise ProblemError(f"{where}: must be at least {minimum}, got {value}")
    return value


def as_number(
    value: Any,
    where: str,
    *,
    above: float | None = None,
    at_least: float | None = None,
    at_most: float | None = None,
) -> float:
    """Return value as a float if it is a finite number within the given limits."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ProblemError(f"{where}: must be a number, got {describe(value)}")
    if not math.isfinite(value):
        raise ProblemError(f"{where}: must be a finite number, got {value}")
    if above is not None and value <= above:
        raise ProblemError(f"{where}: must be above {above:g}, got {value}")
    if at_least is not None and value < at_least:
        raise ProblemError(f"{where}: must be at least {at_least:g}, got {value}")
    if at_most is not None and value > at_most:
        raise ProblemError(f"{where}: must be at most {at_most:g}, got {value}")
    return float(value)


def as_text(value: Any, where: str) -> str:
    """Return value if it is text that is not empty."""
    if not isinstance(value, str) or not value.strip():
        raise ProblemError(f"{where}: must be text that is not empty, got {describe(value)}")
    return value


def as_text_list(value: Any, where: str) -> tuple[str, ...]:
    """Return value as a tuple if it is a list of texts that are not empty."""
    if not isinstance(value, list):
        raise ProblemError(f"{where}: must be a list, got {describe(value)}")
    return tuple(as_text(item, f"{where}[{index}]") for index, item in enumerate(value))


class Section:
    """One mapping of the problem file, read key by key.

    Each method reads one key and marks it as known; finish() then refuses every
    key no method asked for. A key written with no value (null) counts as absent.
    """

    def __init__(self, data: Any, location: str) -> None:
        """Wrap data, which must be a mapping; location names it in error messages."""
        # "" for the top level of the file, such as "llm.models[1]" otherwise.
        self.location: str = location
        if data is None:
            data = {}
        if not isinstance(data, dict):
            raise self.error(f"must be a mapping of keys to values, got {describe(data)}")
        self.data: dict[Any, Any] = data
        self.known: set[Any] = set()

    def error(self, message: str) -> ProblemError:
        """Return an error about this section."""
        return ProblemError(f"{self.location}: {message}" if self.location else message)

    def where(self, key: str) -> str:
        """Return the location of one of this section's keys, such as "llm.timeout"."""
        return f"{self.location}.{key}" if self.location else key

    def get(self, key: str) -> Any:
        """Return the value of a key, or None if it is absent; mark it as known."""
        self.known.add(key)
        return self.data.get(key)

    def required(self, key: str) -> Any:
        """Return the value of a key that must be present."""
        value = self.get(key)
        if value is None:
            raise self.error(f"missing key {key!r}")
        return value

    def integer(self, key: str, default: int, minimum: int) -> int:
        """Return a whole number of at least minimum, or the default."""
        value = self.get(key)
        return default if value is None else as_integer(value, self.where(key), minimum)

    def number(self, key: str, default: float, **limits: float) -> float:
        """Return a number within the limits of as_number, or the default."""
        value = self.get(key)
        return default if value is None else as_number(value, self.where(key), **limits)

    def text(self, key: str, default: str) -> str:
        """Return a text that is not empty, or the default."""
        value = self.get(key)
        return default if value is None else as_text(value, self.where(key))

    def choice(self, key: str, default: str, choices: tuple[str, ...]) -> str:
        """Return one of the given choices, or the default."""
        value = self.text(key, default)
        if value not in choices:
            raise ProblemError(
                f"{self.where(key)}: must be one of {', '.join(choices)}, got {describe(value)}"
            )
        return value

    def section(self, key: str) -> "Section":
        """Return a key's value as a section of its own; absent means empty."""
        return Section(self.get(key), self.where(key))

    def finish(self) -> None:
        """Refuse any key that no method asked for (D44)."""
        unknown = [key for key in self.data if key not in self.known]
        if unknown:
            raise self.error(f"unknown key {unknown[0]!r}")


# ----------------------------------------------------------------------------------
# The settings
# ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvaluationSettings:
    """How programs are evaluated (D9, D41)."""

    # Seconds each cascade stage may take.
    stage_time_limit: float
    # Stage k+1 runs only if stage k's score reaches the k-th threshold.
    thresholds: tuple[float, ...]


@dataclass(frozen=True)
class SandboxSettings:
    """The limits of the container a program runs in (D41)."""

    # Memory, in Docker's notation ("1g"); the same amount without swap.
    memory: str
    # How many CPUs the program may use.
    cpus: float
    # How many processes the program may start.
    max_processes: int


@dataclass(frozen=True)
class PromptSettings:
    """How prompts are written (D10, D30)."""

    # Feedback and errors longer than this, in characters, are cut.
    max_feedback_chars: int


@dataclass(frozen=True)
class ParentSettings:
    """How parents are chosen (D19)."""

    # The strategy's name: "weighted".
    strategy: str
    # λ of the weighted rule: how strongly higher scores are favoured.
    lam: float


@dataclass(frozen=True)
class ModelSettings:
    """One model of the ensemble, with every setting resolved (D31-D35)."""

    # The model's name, as its server knows it.
    name: str
    # How often it is drawn, relative to the other models' weights.
    weight: float
    # The address of its OpenAI-compatible server.
    api_base: str
    # The environment variable holding its API key; None for a server without keys.
    api_key_env: str | None
    # Sent only when set; never for a reasoning model.
    temperature: float | None
    # The longest reply, in tokens.
    max_tokens: int
    # Sent only when set; reasoning models only.
    reasoning_effort: str | None
    # Whether it is a reasoning model (set, or guessed from its name).
    reasoning: bool
    # Seconds to wait for one reply.
    timeout: float
    # How many times the openai package retries a failed request.
    retries: int
    # Prices in money per million tokens, for reporting costs only; None when unknown.
    price_input: float | None
    price_output: float | None


@dataclass(frozen=True)
class LLMSettings:
    """The ensemble of models (D31, D34)."""

    models: tuple[ModelSettings, ...]
    # A model failing this many times in a row is dropped for the rest of the run.
    max_failures_in_a_row: int


@dataclass(frozen=True)
class Problem:
    """A problem and every setting of its runs, as the problem file gives them (D72)."""

    # Short name, used in the run folder's name.
    name: str
    # The task and the contract of the entry functions, shown to the LLM (D4).
    description: str
    # The functions every program must define at the top level (D13).
    entry_functions: tuple[str, ...]
    # The packages programs may import, as "name==version" (D71).
    packages: tuple[str, ...]
    evaluation: EvaluationSettings
    sandbox: SandboxSettings
    prompt: PromptSettings
    parents: ParentSettings
    # Every this many completed iterations, a snapshot of the best program (D47).
    snapshot_every: int
    # This many infrastructure errors in a row stop the run (D38).
    max_errors_in_a_row: int
    llm: LLMSettings

    @property
    def package_names(self) -> tuple[str, ...]:
        """The packages' names without their versions: ("numpy", "scipy")."""
        return tuple(package.split("==", 1)[0] for package in self.packages)

    def fingerprint_without_llm(self) -> str:
        """Return a hash of every setting except the llm section (D50).

        Defaults are filled in before hashing, so writing out a default value does
        not change the fingerprint; changing any value does.
        """
        settings = asdict(self)
        del settings["llm"]
        text = json.dumps(settings, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @classmethod
    def load(cls, path: Path | str) -> "Problem":
        """Read a problem file and return its Problem.

        Raises ProblemError, naming the file, if it cannot be read or used.
        """
        path = Path(path)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as error:
            raise ProblemError(f"{path}: cannot be read ({error.strerror})") from None
        try:
            # UniqueKeyLoader is a safe loader: plain data only, never Python objects.
            data = yaml.load(text, Loader=UniqueKeyLoader)
            if not isinstance(data, dict):
                raise ProblemError(f"must be a mapping of keys to values, got {describe(data)}")
            return cls.from_dict(data)
        except ProblemError as error:
            raise ProblemError(f"{path}: {error}") from None
        except yaml.YAMLError as error:
            raise ProblemError(f"{path}: not valid YAML ({error})") from None

    @classmethod
    def from_dict(cls, data: Any) -> "Problem":
        """Build and check a Problem from the parsed problem file (used by load and the tests)."""
        top = Section(data, "")
        problem = cls(
            name=read_name(top),
            description=as_text(top.required("description"), "description"),
            entry_functions=read_entry_functions(top),
            packages=read_packages(top),
            evaluation=read_evaluation(top.section("evaluation")),
            sandbox=read_sandbox(top.section("sandbox")),
            prompt=read_prompt(top.section("prompt")),
            parents=read_parents(top.section("parents")),
            snapshot_every=top.integer("snapshot_every", DEFAULT_SNAPSHOT_EVERY, minimum=1),
            max_errors_in_a_row=top.integer(
                "max_errors_in_a_row", DEFAULT_MAX_ERRORS_IN_A_ROW, minimum=1
            ),
            llm=build_llm(Section(top.required("llm"), "llm")),
        )
        top.finish()
        return problem


# ----------------------------------------------------------------------------------
# Reading each part
# ----------------------------------------------------------------------------------


def read_name(top: Section) -> str:
    """Return the problem's name: letters, digits, "-" and "_" only."""
    name = as_text(top.required("name"), "name")
    if not NAME_PATTERN.fullmatch(name):
        raise ProblemError(f"name: only letters, digits, '-' and '_' are allowed, got {name!r}")
    return name


def read_entry_functions(top: Section) -> tuple[str, ...]:
    """Return the entry functions: a non-empty list of distinct Python names."""
    names = as_text_list(top.required("entry_functions"), "entry_functions")
    if not names:
        raise ProblemError("entry_functions: must name at least one function")
    for index, name in enumerate(names):
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ProblemError(f"entry_functions[{index}]: not a Python name, got {name!r}")
    if len(set(names)) < len(names):
        raise ProblemError("entry_functions: a function is listed twice")
    return names


def read_packages(top: Section) -> tuple[str, ...]:
    """Return the packages programs may import, each as "name==version" (D71)."""
    value = top.get("packages")
    packages = as_text_list(value, "packages") if value is not None else ()
    seen: set[str] = set()
    for index, package in enumerate(packages):
        where = f"packages[{index}]"
        if package.startswith("-"):
            raise ProblemError(f"{where}: only packages may be listed, not pip options")
        match = PACKAGE_PATTERN.fullmatch(package)
        if match is None:
            raise ProblemError(f"{where}: must be name==version, such as numpy==2.5.4")
        # pip treats "-", "_" and "." alike, and ignores letter case.
        name = re.sub(r"[-_.]+", "-", match["name"]).lower()
        if name in seen:
            raise ProblemError(f"{where}: {match['name']} is listed twice")
        seen.add(name)
    return packages


def read_evaluation(section: Section) -> EvaluationSettings:
    """Return the evaluation section's settings."""
    value = section.get("thresholds")
    where = section.where("thresholds")
    if value is not None and not isinstance(value, list):
        raise ProblemError(f"{where}: must be a list, got {describe(value)}")
    settings = EvaluationSettings(
        stage_time_limit=section.number("stage_time_limit", DEFAULT_STAGE_TIME_LIMIT, above=0),
        thresholds=tuple(
            as_number(threshold, f"{where}[{index}]") for index, threshold in enumerate(value or [])
        ),
    )
    section.finish()
    return settings


def read_sandbox(section: Section) -> SandboxSettings:
    """Return the sandbox section's settings."""
    memory = section.text("memory", DEFAULT_MEMORY)
    if not MEMORY_PATTERN.fullmatch(memory):
        raise ProblemError(
            f"{section.where('memory')}: must be a whole number and k, m or g, such as 1g, "
            f"got {memory!r}"
        )
    settings = SandboxSettings(
        memory=memory,
        cpus=section.number("cpus", DEFAULT_CPUS, above=0),
        max_processes=section.integer("max_processes", DEFAULT_MAX_PROCESSES, minimum=1),
    )
    section.finish()
    return settings


def read_prompt(section: Section) -> PromptSettings:
    """Return the prompt section's settings."""
    settings = PromptSettings(
        max_feedback_chars=section.integer(
            "max_feedback_chars", DEFAULT_MAX_FEEDBACK_CHARS, minimum=1
        ),
    )
    section.finish()
    return settings


def read_parents(section: Section) -> ParentSettings:
    """Return the parents section's settings."""
    settings = ParentSettings(
        strategy=section.choice("strategy", DEFAULT_PARENT_STRATEGY, PARENT_STRATEGIES),
        lam=section.number("lambda", DEFAULT_LAMBDA, at_least=0),
    )
    section.finish()
    return settings


def parse_key(value: Any, where: str) -> str | None:
    """Return the name of the environment variable holding a model's API key (D46).

    None means no key (a local server). The key itself is refused, and never
    repeated in the error, so that it cannot end up on the console or in a log.
    """
    if value is None:
        return None
    match = KEY_VARIABLE_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise ProblemError(
            f"{where}: write api_key: ${{VARIABLE}}, naming the environment variable that "
            "holds the key; never the key itself"
        )
    return match["name"]


def build_llm(section: Section) -> LLMSettings:
    """Return the llm section's models, each with its own and the shared settings merged.

    A model's own value wins over the shared one, which wins over the default.
    """
    shared = {key: section.get(key) for key in SHARED_MODEL_KEYS}
    max_failures = section.integer(
        "max_failures_in_a_row", DEFAULT_MAX_FAILURES_IN_A_ROW, minimum=1
    )
    models_value = section.required("models")
    if not isinstance(models_value, list) or not models_value:
        raise ProblemError("llm.models: must be a list of at least one model")
    section.finish()

    models = tuple(
        build_model(Section(model_data, f"llm.models[{index}]"), shared)
        for index, model_data in enumerate(models_value)
    )
    names = [model.name for model in models]
    for index, name in enumerate(names):
        if name in names[:index]:
            raise ProblemError(f"llm.models[{index}]: the model {name!r} is listed twice")
    return LLMSettings(models=models, max_failures_in_a_row=max_failures)


def build_model(model: Section, shared: dict[str, Any]) -> ModelSettings:
    """Return one model's settings: its own values, else the shared ones, else the defaults."""

    def value_of(key: str) -> tuple[Any, str]:
        """Return a setting's value and where it was written."""
        value = model.get(key)
        if value is not None:
            return value, model.where(key)
        return shared[key], f"llm.{key}"

    def number_or_none(key: str, **limits: float) -> float | None:
        value, where = value_of(key)
        return None if value is None else as_number(value, where, **limits)

    name = as_text(model.required("name"), model.where("name"))
    weight = model.number("weight", DEFAULT_WEIGHT, above=0)

    api_base, where = value_of("api_base")
    if api_base is None:
        raise model.error("no api_base, neither for this model nor in llm")
    api_base = as_text(api_base, where)

    api_key, where = value_of("api_key")
    api_key_env = parse_key(api_key, where)

    max_tokens, where = value_of("max_tokens")
    max_tokens = DEFAULT_MAX_TOKENS if max_tokens is None else as_integer(max_tokens, where, 1)

    reasoning_effort, where = value_of("reasoning_effort")
    if reasoning_effort is not None:
        reasoning_effort = as_text(reasoning_effort, where)

    reasoning, where = value_of("reasoning")
    if reasoning is None:
        reasoning = is_reasoning_model(name)
    elif not isinstance(reasoning, bool):
        raise ProblemError(f"{where}: must be true or false, got {describe(reasoning)}")

    timeout = number_or_none("timeout", above=0)
    retries, where = value_of("retries")
    retries = DEFAULT_RETRIES if retries is None else as_integer(retries, where, 0)
    temperature = number_or_none("temperature", at_least=0, at_most=2)
    price_input = number_or_none("price_input", at_least=0)
    price_output = number_or_none("price_output", at_least=0)
    model.finish()

    if reasoning and temperature is not None:
        raise model.error(f"{name} is a reasoning model, which refuses a temperature")
    if not reasoning and reasoning_effort is not None:
        raise model.error(f"{name} is not a reasoning model, so it takes no reasoning_effort")
    if (price_input is None) != (price_output is None):
        raise model.error("set both price_input and price_output, or neither")

    return ModelSettings(
        name=name,
        weight=weight,
        api_base=api_base,
        api_key_env=api_key_env,
        temperature=temperature,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        reasoning=reasoning,
        timeout=DEFAULT_TIMEOUT if timeout is None else timeout,
        retries=retries,
        price_input=price_input,
        price_output=price_output,
    )
