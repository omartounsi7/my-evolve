"""The Problem class: what to solve, and the settings of its runs, read from the problem file.

The problem file is written in YAML. For now it holds:

    name: circle_packing
    description: |
      What the program must do, shown to the LLM in every prompt.
    entry_functions: [run_packing]         # the functions every program must define
    packages: [numpy==2.5.4]               # optional: what programs may import, exact versions
    snapshot_every: 10                     # optional: completed iterations between snapshots
    max_errors_in_a_row: 3                 # optional: errors (not the program's fault) that
                                           #   stop the run when they come in a row
    llm:                                   # laid out like openevolve's llm section
      api_base: http://localhost:11434/v1  # the server's OpenAI-compatible address
      api_key: ${ANTHROPIC_API_KEY}        # optional: the variable holding the key
      max_tokens: 16384                    # optional: the longest reply, in tokens
      context_length: 32768                # optional: the prompt and the reply must fit in it
      temperature: 0.7                     # optional; not for reasoning models
      reasoning_effort: medium             # optional; reasoning models only
      timeout: 300                         # optional: seconds to wait for a reply
      retries: 2                           # optional: retries of a failed request
      price_input: 1.0                     # optional: dollars per million input tokens
      price_output: 5.0                    # optional: per million output tokens (reports only)
      max_failures_in_a_row: 3             # optional: a model failing this often is dropped
      models:                              # the ensemble: one model is drawn per iteration
        - name: qwen3-coder:30b            # the model's name, as its server knows it
          weight: 0.8                      # optional (1): how often it is drawn, relatively
        - name: qwen3:8b
          weight: 0.2
          reasoning: false                 # optional; guessed from the name if absent
          max_tokens: 24576                # any shared key, for this model only
    evaluation:                            # optional
      stage_time_limit: 60                 # seconds each cascade stage may take
      thresholds: [0.5]                    # stage k + 1 runs if stage k's score reaches the k-th
    islands:                               # optional (D23)
      count: 3                             # islands, each with its own MAP-Elites grid
      migration_interval: 25               # completed iterations between two migrations
      migration_share: 0.1                 # the share of each island's elites that migrate
      migrants: random_non_best            # or best, or random
      destinations: all_others             # or ring: the next island only
      mode: copy                           # or move: the migrant leaves its island
    grid:                                  # optional: the grid of each island (D17, D18)
      features:                            # its dimensions, 1 to 3
        - name: code_complexity            # nodes inside the evolve blocks, as log2 of
          low: -1                          #   their ratio to the initial program's
          high: 3                          # values outside low..high go to the end bins
          bins: 10                         # optional: 10, 5 or 3 for 1, 2 or 3 features
        - name: radii_spread               # any other name: an output feature, which
          low: 0                           #   the evaluation's stage 1 must give
          high: 1
    parents:                               # optional: how parents are chosen (D19)
      strategy: weighted                   # ShinkaEvolve's rule, or openevolve
      lambda: 1.0                          # weighted: how sharply it favours better programs
      archive_size: 10                     # openevolve: the best programs it draws from
    prompt:                                # optional
      example_programs: 2                  # other programs shown besides the parent
      max_chars: 60000                     # the longest prompt, in characters
      max_feedback_chars: 2000             # feedback and errors are cut to this length
    sandbox:                               # optional: the limits of the Docker sandbox
      memory: 1g                           # memory, without swap (Docker's notation)
      cpus: 1                              # CPUs
      max_processes: 64                    # processes and threads

Every key is checked, and an unknown key is an error rather than silently ignored.
"""

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# An amount of memory in Docker's notation, such as "1g" or "512m"
MEMORY_PATTERN = re.compile(r"[0-9]+(\.[0-9]+)?[bkmg]?")
# A key written as the variable holding it, such as ${ANTHROPIC_API_KEY}
KEY_VARIABLE_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
# The beginnings of the names of OpenAI's reasoning models, which refuse max_tokens and
# temperature and need max_completion_tokens (as openevolve guesses them)
REASONING_MODEL_PREFIXES = ("o1", "o3", "o4", "gpt-5", "gpt-oss")
# The rules that can choose parents; the first is the default
PARENT_STRATEGIES = ("weighted", "openevolve")
# The choices of a migration (D23); the first of each is the default
MIGRANT_CHOICES = ("random_non_best", "best", "random")
DESTINATION_CHOICES = ("all_others", "ring")
MIGRATION_MODES = ("copy", "move")
# The grid's built-in feature: the syntax-tree nodes inside the evolve blocks (D17)
CODE_COMPLEXITY = "code_complexity"
# The most dimensions a grid may have, and each feature's bins when the problem file
# gives none, by number of dimensions: grids stay small for runs of a few hundred
# iterations (D18)
MAX_GRID_FEATURES = 3
DEFAULT_BINS = {1: 10, 2: 5, 3: 3}
# The keys of the llm section that apply to every model, unless a model sets its own
SHARED_MODEL_KEYS = frozenset(
    {
        "api_base",
        "api_key",
        "max_tokens",
        "temperature",
        "reasoning_effort",
        "timeout",
        "retries",
        "price_input",
        "price_output",
        "context_length",
    }
)
# How many characters of prompt a token holds, at the least: 3.55 to 4.49 in the 110 calls
# of the first plan's milestones (code and English, Qwen's tokenizer). Kept low, so that
# the estimate of a prompt's tokens errs on the high side
CHARS_PER_TOKEN = 3.5
# A package with its exact version, such as "numpy==2.5.4": nothing else is accepted
PACKAGE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9][A-Za-z0-9.+!_-]*")


class ProblemError(ValueError):
    """Raised when a problem file cannot be read or breaks a rule; the message says why."""


@dataclass(frozen=True)
class ModelSettings:
    """A model that writes programs: where to reach it, and how to ask it (D32, D33)."""

    # The model's name, as its server knows it
    name: str
    # The address of the server's OpenAI-compatible interface
    api_base: str
    # The environment variable holding the API key; None for a server that needs none
    api_key_env: str | None = None
    # The longest reply, in tokens: enough for a reasoning model's thinking and its reply
    max_tokens: int = 16_384
    # The sampling temperature; None to leave it to the server
    temperature: float | None = None
    # How hard a reasoning model thinks ("low", "medium", "high", ...); None for its default
    reasoning_effort: str | None = None
    # True for a reasoning model, which takes max_completion_tokens and no temperature
    reasoning: bool = False
    # How long to wait for one reply, in seconds
    timeout: float = 300.0
    # How many times the openai package retries a failed request: the only layer of retries
    retries: int = 2
    # Its prices in dollars per million input and output tokens, for the run's summary
    # only (D35); None when not given
    price_input: float | None = None
    price_output: float | None = None
    # How often the ensemble draws it, relative to the other models' weights
    weight: float = 1.0
    # The tokens its server can hold, the prompt and the reply together; None if not given.
    # A server such as Ollama silently cuts a prompt that does not fit, so the prompt's
    # budget plus max_tokens must fit in it
    context_length: int | None = None


@dataclass(frozen=True)
class LLMSettings:
    """The ensemble of models that write the programs (D31, D34)."""

    # The models, each with its weight
    models: tuple[ModelSettings, ...]
    # A model failing this many times in a row is dropped for the rest of the run
    max_failures_in_a_row: int = 3


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
class FeatureSpec:
    """One dimension of the MAP-Elites grid (D17, D18)."""

    # The feature's name: code_complexity, built in, or an output feature, which the
    # evaluation file's stage 1 gives
    name: str
    # The range cut into equal bins; a value outside it goes to the nearest end bin
    low: float
    high: float
    # How many bins
    bins: int


# The grid when the problem file gives none: code complexity, from half to eight times the
# initial program's size, in 10 bins (D18)
DEFAULT_GRID = (FeatureSpec(CODE_COMPLEXITY, -1.0, 3.0, 10),)


@dataclass(frozen=True)
class IslandSettings:
    """The islands: populations that evolve apart, and the migrations between them (D23)."""

    # How many islands there are
    count: int = 3
    # How many completed iterations pass between two migrations
    migration_interval: int = 25
    # The share of each island's elites that migrate (at least one)
    migration_share: float = 0.1
    # Which elites migrate: "random_non_best" (any but the island's best), "best" or "random"
    migrants: str = "random_non_best"
    # Where they go: "all_others" (every other island) or "ring" (the next island)
    destinations: str = "all_others"
    # "copy" (the migrant also stays) or "move" (it leaves its island's grid)
    mode: str = "copy"


@dataclass(frozen=True)
class ParentSettings:
    """How parents are chosen (D19)."""

    # The rule: "weighted", ShinkaEvolve's, or "openevolve"
    strategy: str = "weighted"
    # How sharply the weighted rule favours programs above the median (λ; ShinkaEvolve: 10)
    lam: float = 1.0
    # How many of the run's best programs form the archive openevolve's rule draws from (D21)
    archive_size: int = 10


@dataclass(frozen=True)
class PromptSettings:
    """What the prompt shows."""

    # How many example programs the prompt shows besides the parent (D26)
    example_programs: int = 2
    # The longest prompt, both messages together, in characters (D30)
    max_chars: int = 60_000
    # The longest feedback or error shown for one program, in characters
    max_feedback_chars: int = 2000


@dataclass(frozen=True)
class Problem:
    """A problem to solve, and every setting of its runs."""

    # A short name, used to name the run folders
    name: str
    # What the program must do, including the contract of its entry functions
    description: str
    # The models that write the programs
    llm: LLMSettings
    # The packages programs may import besides the standard library, such as "numpy==2.5.4"
    packages: tuple[str, ...] = ()
    # The functions every program must define at its top level, such as ("run_packing",)
    entry_functions: tuple[str, ...] = ()
    # How many completed iterations pass between two snapshots of the best program (D47)
    snapshot_every: int = 10
    # How many iterations in a row ending in an error, not the program's fault, stop the run
    max_errors_in_a_row: int = 3
    # How programs are evaluated
    evaluation: EvaluationSettings = field(default_factory=EvaluationSettings)
    # The limits of the Docker sandbox
    sandbox: SandboxSettings = field(default_factory=SandboxSettings)
    # What the prompt shows
    prompt: PromptSettings = field(default_factory=PromptSettings)
    # How parents are chosen
    parents: ParentSettings = field(default_factory=ParentSettings)
    # The islands
    islands: IslandSettings = field(default_factory=IslandSettings)
    # The dimensions of each island's MAP-Elites grid
    grid_features: tuple[FeatureSpec, ...] = DEFAULT_GRID

    @property
    def output_feature_names(self) -> tuple[str, ...]:
        """Return the grid's features other than code_complexity: those the evaluation gives."""
        return tuple(
            feature.name for feature in self.grid_features if feature.name != CODE_COMPLEXITY
        )

    def fingerprint_without_llm(self) -> str:
        """Return a hash of every setting but the llm section (D50).

        The settings are hashed once read, in a fixed order, so that a comment or the
        layout of the file changes nothing, while a default spelled out changes nothing
        either.
        """
        settings = asdict(self)
        del settings["llm"]
        text = json.dumps(settings, sort_keys=True, allow_nan=False)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

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
            optional={
                "packages",
                "snapshot_every",
                "max_errors_in_a_row",
                "evaluation",
                "sandbox",
                "prompt",
                "parents",
                "islands",
                "grid",
            },
        )
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
            top.get("prompt", {}),
            "the prompt section",
            optional={"example_programs", "max_chars", "max_feedback_chars"},
        )
        prompt_defaults = PromptSettings()
        islands = checked_section(
            top.get("islands", {}),
            "the islands section",
            optional={
                "count",
                "migration_interval",
                "migration_share",
                "migrants",
                "destinations",
                "mode",
            },
        )
        island_defaults = IslandSettings()
        share = checked_positive_number(
            islands, "migration_share", "the islands section", island_defaults.migration_share
        )
        if share > 1:
            raise ProblemError(
                f"'migration_share' in the islands section must be at most 1, got {share}"
            )
        parents = checked_section(
            top.get("parents", {}),
            "the parents section",
            optional={"strategy", "lambda", "archive_size"},
        )
        defaults = EvaluationSettings()
        sandbox_defaults = SandboxSettings()
        problem = cls(
            name=checked_text(top, "name", "the problem file"),
            description=checked_text(top, "description", "the problem file"),
            entry_functions=checked_entry_functions(top["entry_functions"]),
            snapshot_every=checked_count(top, "snapshot_every", "the problem file", 10),
            max_errors_in_a_row=checked_count(top, "max_errors_in_a_row", "the problem file", 3),
            llm=build_llm(top["llm"]),
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
                example_programs=checked_count(
                    prompt,
                    "example_programs",
                    "the prompt section",
                    prompt_defaults.example_programs,
                    minimum=0,
                ),
                max_chars=checked_count(
                    prompt, "max_chars", "the prompt section", prompt_defaults.max_chars
                ),
                max_feedback_chars=checked_count(
                    prompt,
                    "max_feedback_chars",
                    "the prompt section",
                    prompt_defaults.max_feedback_chars,
                ),
            ),
            parents=ParentSettings(
                strategy=checked_choice(
                    parents, "strategy", "the parents section", PARENT_STRATEGIES
                ),
                lam=checked_positive_number(
                    parents, "lambda", "the parents section", ParentSettings().lam
                ),
                archive_size=checked_count(
                    parents, "archive_size", "the parents section", ParentSettings().archive_size
                ),
            ),
            grid_features=build_grid(top.get("grid", {})),
            islands=IslandSettings(
                count=checked_count(islands, "count", "the islands section", island_defaults.count),
                migration_interval=checked_count(
                    islands,
                    "migration_interval",
                    "the islands section",
                    island_defaults.migration_interval,
                ),
                migration_share=share,
                migrants=checked_choice(
                    islands, "migrants", "the islands section", MIGRANT_CHOICES
                ),
                destinations=checked_choice(
                    islands, "destinations", "the islands section", DESTINATION_CHOICES
                ),
                mode=checked_choice(islands, "mode", "the islands section", MIGRATION_MODES),
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
        check_context(problem.llm, problem.prompt.max_chars)
        return problem


def prompt_tokens(characters: int) -> int:
    """Return how many tokens a prompt of that many characters takes, at the most likely."""
    return math.ceil(characters / CHARS_PER_TOKEN)


def check_context(llm: LLMSettings, max_chars: int) -> None:
    """Refuse a model whose context cannot hold the longest prompt and the longest reply.

    The prompt's tokens are estimated from the prompt section's max_chars. Raises
    ProblemError, saying what to lower, for the first model whose context is too small.
    """
    for model in llm.models:
        if model.context_length is None:
            continue
        needed = prompt_tokens(max_chars) + model.max_tokens
        if needed > model.context_length:
            raise ProblemError(
                f"{model.name}'s context_length of {model.context_length} tokens cannot hold "
                f"the longest prompt (max_chars {max_chars}, about {prompt_tokens(max_chars)} "
                f"tokens) and the longest reply (max_tokens {model.max_tokens}): {needed} "
                "tokens. Lower max_chars in the prompt section, or the model's max_tokens"
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


def is_reasoning_model(name: str) -> bool:
    """Guess from its name whether a model is one of OpenAI's reasoning models.

    The name is read without any provider prefix, such as "openai/".
    """
    return name.rsplit("/", 1)[-1].lower().startswith(REASONING_MODEL_PREFIXES)


def parse_key(value: Any) -> str | None:
    """Return the name of the environment variable holding the API key (D46).

    No value: no key, for a local server. "${NAME}": the variable NAME. Anything else is
    refused, so that a key is never written in a problem file.
    """
    if value is None:
        return None
    found = KEY_VARIABLE_PATTERN.fullmatch(value) if isinstance(value, str) else None
    if found is None:
        raise ProblemError(
            "'api_key' must name the environment variable holding the key, such as "
            "${ANTHROPIC_API_KEY}; never write the key itself in the problem file"
        )
    return found.group(1)


def checked_optional_number(section: dict[str, Any], key: str, where: str) -> float | None:
    """Return the value of a key that may hold a finite number, or None if it is absent."""
    value = section.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ProblemError(f"{key!r} in {where} must be a number, got {value!r}")
    return float(value)


def build_llm(section: Any) -> LLMSettings:
    """Build the ensemble's settings from the llm section, checking every value (D72).

    The section's values other than models and max_failures_in_a_row apply to every
    model; a model's own value wins over them, as in openevolve.
    """
    where = "the llm section"
    llm = checked_section(
        section, where, required={"models"}, optional=SHARED_MODEL_KEYS | {"max_failures_in_a_row"}
    )
    shared = {key: value for key, value in llm.items() if key in SHARED_MODEL_KEYS}
    entries = llm["models"]
    if not isinstance(entries, list) or not entries:
        raise ProblemError("'models' in the llm section must be a list of one model or more")
    models = []
    for number, entry in enumerate(entries, start=1):
        own = checked_section(
            entry,
            f"model {number} of the llm section",
            required={"name"},
            optional=SHARED_MODEL_KEYS | {"weight", "reasoning"},
        )
        models.append(build_model({**shared, **own}, f"model {number} of the llm section"))
    names = [model.name for model in models]
    if len(set(names)) != len(names):
        raise ProblemError("two models of the llm section have the same name")
    return LLMSettings(
        models=tuple(models),
        max_failures_in_a_row=checked_count(
            llm, "max_failures_in_a_row", where, LLMSettings(models=()).max_failures_in_a_row
        ),
    )


def build_model(values: dict[str, Any], where: str) -> ModelSettings:
    """Build one model's settings from its merged values, checking every value."""
    llm = values
    if "api_base" not in llm:
        raise ProblemError(f"missing key 'api_base' for {where}, or in the llm section")
    defaults = ModelSettings(name="", api_base="")
    name = checked_text(llm, "name", where)
    reasoning = llm.get("reasoning", is_reasoning_model(name))
    if not isinstance(reasoning, bool):
        raise ProblemError(f"'reasoning' in {where} must be true or false, got {reasoning!r}")
    temperature = checked_optional_number(llm, "temperature", where)
    effort = llm.get("reasoning_effort")
    if effort is not None and not (isinstance(effort, str) and effort.strip()):
        raise ProblemError(f"'reasoning_effort' in {where} must be some text, got {effort!r}")
    if reasoning and temperature is not None:
        raise ProblemError(
            f"{name} is a reasoning model, which refuses a temperature: remove 'temperature', "
            "or set 'reasoning: false' if it is not one"
        )
    if not reasoning and effort is not None:
        raise ProblemError(
            f"'reasoning_effort' is for reasoning models only, and {name} is not one "
            "(set 'reasoning: true' if it is)"
        )
    return ModelSettings(
        name=name,
        api_base=checked_text(llm, "api_base", where),
        api_key_env=parse_key(llm.get("api_key")),
        max_tokens=checked_count(llm, "max_tokens", where, defaults.max_tokens),
        temperature=temperature,
        reasoning_effort=effort,
        reasoning=reasoning,
        timeout=checked_positive_number(llm, "timeout", where, defaults.timeout),
        retries=checked_count(llm, "retries", where, defaults.retries, minimum=0),
        price_input=checked_optional_number(llm, "price_input", where),
        price_output=checked_optional_number(llm, "price_output", where),
        weight=checked_positive_number(llm, "weight", where, defaults.weight),
        context_length=(
            checked_count(llm, "context_length", where, 1) if "context_length" in llm else None
        ),
    )


def checked_choice(section: dict[str, Any], key: str, where: str, choices: tuple[str, ...]) -> str:
    """Return the value of a key that must be one of choices; the first one if absent."""
    value = section.get(key, choices[0])
    if value not in choices:
        raise ProblemError(f"{key!r} in {where} must be one of {', '.join(choices)}, got {value!r}")
    return str(value)


def checked_number(section: dict[str, Any], key: str, where: str) -> float:
    """Return the value of a required key that must hold a finite number."""
    value = checked_optional_number(section, key, where)
    if value is None:
        raise ProblemError(f"{key!r} in {where} must be a number")
    return value


def build_grid(section: Any) -> tuple[FeatureSpec, ...]:
    """Build the grid's dimensions from the grid section; code_complexity alone by default.

    Each feature has a name (code_complexity, or an output feature the evaluation gives),
    a range (low below high) and a number of bins; without one, 10, 5 or 3 bins for a grid
    of 1, 2 or 3 features (D18).
    """
    grid = checked_section(section, "the grid section", optional={"features"})
    if "features" not in grid:
        return DEFAULT_GRID
    entries = grid["features"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_GRID_FEATURES:
        raise ProblemError(
            f"'features' in the grid section must be a list of 1 to {MAX_GRID_FEATURES} features"
        )
    features = []
    for number, entry in enumerate(entries, start=1):
        where = f"feature {number} of the grid section"
        spec = checked_section(entry, where, required={"name", "low", "high"}, optional={"bins"})
        name = checked_text(spec, "name", where)
        low = checked_number(spec, "low", where)
        high = checked_number(spec, "high", where)
        if not low < high:
            raise ProblemError(f"'low' must be below 'high' in {where}")
        bins = checked_count(spec, "bins", where, DEFAULT_BINS[len(entries)])
        features.append(FeatureSpec(name, low, high, bins))
    if len({feature.name for feature in features}) != len(features):
        raise ProblemError("two features of the grid section have the same name")
    return tuple(features)


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


def checked_count(
    section: dict[str, Any], key: str, where: str, default: int, minimum: int = 1
) -> int:
    """Return the value of a key holding a whole number of at least minimum, or the default."""
    value = section.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProblemError(
            f"{key!r} in {where} must be a whole number of {minimum} or more, got {value!r}"
        )
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
