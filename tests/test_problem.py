"""Checks that problem files are read into a Problem, with every value checked."""

import copy
import tempfile
import unittest
from pathlib import Path
from typing import Any

from my_evolve.llm import is_reasoning_model
from my_evolve.problem import Problem, ProblemError

# A complete problem file, with a value written for every key.
COMPLETE_FILE = """\
name: circle_packing
description: |
  Pack 26 circles in the unit square.
  run_packing() returns the centres, the radii and their sum.
entry_functions: [run_packing]
packages: [numpy==2.5.4, scipy==1.18.1]
snapshot_every: 5
max_errors_in_a_row: 4
evaluation:
  stage_time_limit: 90
  thresholds: [0.5]
sandbox:
  memory: 2g
  cpus: 2
  max_processes: 32
prompt:
  max_feedback_chars: 1000
parents:
  strategy: weighted
  lambda: 2
llm:
  api_base: https://api.anthropic.com/v1/
  api_key: ${ANTHROPIC_API_KEY}
  max_tokens: 8000
  timeout: 120
  retries: 1
  max_failures_in_a_row: 5
  models:
    - name: claude-haiku-5-5
      weight: 0.8
      price_input: 1
      price_output: 5
    - name: claude-sonnet-5-5
      weight: 0.2
      timeout: 600
"""


def minimal() -> dict[str, Any]:
    """Return the smallest valid problem, as parsed data."""
    return {
        "name": "test",
        "description": "Return a large number.",
        "entry_functions": ["run"],
        "llm": {"models": [{"name": "qwen3:8b", "api_base": "http://localhost:11434/v1"}]},
    }


def changed(path: str, value: Any) -> dict[str, Any]:
    """Return the minimal problem with one value set; path is like "llm.models.0.weight"."""
    data = minimal()
    target: Any = data
    *parents, last = path.split(".")
    for part in parents:
        if isinstance(target, list):
            target = target[int(part)]
        else:
            target = target.setdefault(part, {})
    if isinstance(target, list):
        target[int(last)] = value
    else:
        target[last] = value
    return data


def first_model(data: dict[str, Any]) -> Any:
    """Return the settings of the first model of a problem."""
    return Problem.from_dict(data).llm.models[0]


class TestLoadingFiles(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def write(self, text: str) -> Path:
        path = self.folder / "problem.yaml"
        path.write_text(text, encoding="utf-8")
        return path

    def test_complete_file_keeps_every_value(self) -> None:
        problem = Problem.load(self.write(COMPLETE_FILE))
        self.assertEqual(problem.name, "circle_packing")
        self.assertIn("run_packing() returns", problem.description)
        self.assertEqual(problem.entry_functions, ("run_packing",))
        self.assertEqual(problem.packages, ("numpy==2.5.4", "scipy==1.18.1"))
        self.assertEqual(problem.package_names, ("numpy", "scipy"))
        self.assertEqual((problem.snapshot_every, problem.max_errors_in_a_row), (5, 4))
        self.assertEqual(problem.evaluation.stage_time_limit, 90)
        self.assertEqual(problem.evaluation.thresholds, (0.5,))
        self.assertEqual(problem.sandbox.memory, "2g")
        self.assertEqual((problem.sandbox.cpus, problem.sandbox.max_processes), (2, 32))
        self.assertEqual(problem.prompt.max_feedback_chars, 1000)
        self.assertEqual((problem.parents.strategy, problem.parents.lam), ("weighted", 2))
        self.assertEqual(problem.llm.max_failures_in_a_row, 5)
        haiku, sonnet = problem.llm.models
        self.assertEqual((haiku.name, haiku.weight), ("claude-haiku-5-5", 0.8))
        self.assertEqual(haiku.api_base, "https://api.anthropic.com/v1/")
        self.assertEqual(haiku.api_key_env, "ANTHROPIC_API_KEY")
        self.assertEqual((haiku.max_tokens, haiku.timeout, haiku.retries), (8000, 120, 1))
        self.assertEqual((haiku.price_input, haiku.price_output), (1, 5))
        self.assertEqual(sonnet.timeout, 600)
        self.assertIsNone(sonnet.price_input)

    def test_byte_order_mark_is_ignored(self) -> None:
        path = self.folder / "problem.yaml"
        path.write_text("﻿" + COMPLETE_FILE, encoding="utf-8")
        self.assertEqual(Problem.load(path).name, "circle_packing")

    def test_empty_file_is_refused_naming_it(self) -> None:
        with self.assertRaisesRegex(ProblemError, r"problem\.yaml: must be a mapping"):
            Problem.load(self.write(""))

    def test_file_holding_a_list_is_refused(self) -> None:
        with self.assertRaisesRegex(ProblemError, "must be a mapping"):
            Problem.load(self.write("- name: test\n"))

    def test_repeated_key_is_refused(self) -> None:
        with self.assertRaisesRegex(ProblemError, r"line 2: the key 'name' appears twice"):
            Problem.load(self.write("name: one\nname: two\n"))

    def test_invalid_yaml_is_refused(self) -> None:
        with self.assertRaisesRegex(ProblemError, "not valid YAML"):
            Problem.load(self.write("name: [unclosed\n"))

    def test_python_objects_are_never_built(self) -> None:
        with self.assertRaisesRegex(ProblemError, "not valid YAML"):
            Problem.load(self.write("name: !!python/object/apply:os.system ['echo hi']\n"))

    def test_missing_file_is_reported(self) -> None:
        with self.assertRaisesRegex(ProblemError, "cannot be read"):
            Problem.load(self.folder / "absent.yaml")


class TestDefaults(unittest.TestCase):
    def test_minimal_problem_gets_every_default(self) -> None:
        problem = Problem.from_dict(minimal())
        self.assertEqual(problem.packages, ())
        self.assertEqual((problem.snapshot_every, problem.max_errors_in_a_row), (10, 3))
        self.assertEqual(problem.evaluation.stage_time_limit, 60)
        self.assertEqual(problem.evaluation.thresholds, ())
        self.assertEqual(problem.sandbox.memory, "1g")
        self.assertEqual((problem.sandbox.cpus, problem.sandbox.max_processes), (1, 64))
        self.assertEqual(problem.prompt.max_feedback_chars, 2000)
        self.assertEqual((problem.parents.strategy, problem.parents.lam), ("weighted", 1))
        self.assertEqual(problem.llm.max_failures_in_a_row, 3)
        model = problem.llm.models[0]
        self.assertEqual(model.weight, 1)
        self.assertIsNone(model.api_key_env)
        self.assertEqual((model.max_tokens, model.timeout, model.retries), (16384, 300, 2))
        self.assertIsNone(model.temperature)
        self.assertIsNone(model.reasoning_effort)
        self.assertFalse(model.reasoning)

    def test_key_written_without_a_value_counts_as_absent(self) -> None:
        self.assertIsNone(first_model(changed("llm.temperature", None)).temperature)


class TestUnknownAndMissingKeys(unittest.TestCase):
    def test_unknown_key_is_refused_at_every_level(self) -> None:
        cases = {
            "grid": "unknown key 'grid'",
            "sandbox.gpu": "sandbox: unknown key 'gpu'",
            "llm.top_p": "llm: unknown key 'top_p'",
            "llm.models.0.seed": r"llm\.models\[0\]: unknown key 'seed'",
        }
        for path, message in cases.items():
            with self.subTest(path=path), self.assertRaisesRegex(ProblemError, message):
                Problem.from_dict(changed(path, 1))

    def test_missing_required_key_is_named(self) -> None:
        for key in ("name", "description", "entry_functions", "llm"):
            data = minimal()
            del data[key]
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(ProblemError, f"missing key '{key}'"),
            ):
                Problem.from_dict(data)

    def test_model_without_a_name_is_refused(self) -> None:
        data = minimal()
        del data["llm"]["models"][0]["name"]
        with self.assertRaisesRegex(ProblemError, r"llm\.models\[0\]: missing key 'name'"):
            Problem.from_dict(data)

    def test_section_that_is_not_a_mapping_is_refused(self) -> None:
        with self.assertRaisesRegex(ProblemError, "sandbox: must be a mapping"):
            Problem.from_dict(changed("sandbox", [1, 2]))


class TestValues(unittest.TestCase):
    def assert_refused(self, path: str, value: Any, message: str) -> None:
        with self.subTest(path=path, value=value), self.assertRaisesRegex(ProblemError, message):
            Problem.from_dict(changed(path, value))

    def test_wrong_types_are_refused(self) -> None:
        self.assert_refused("snapshot_every", "10", "must be a whole number")
        self.assert_refused("snapshot_every", True, "must be a whole number")
        self.assert_refused("snapshot_every", 2.5, "must be a whole number")
        self.assert_refused("sandbox.cpus", "1", "must be a number")
        self.assert_refused("sandbox.cpus", True, "must be a number")
        self.assert_refused("description", ["a", "b"], "must be text")
        self.assert_refused("description", "   ", "must be text that is not empty")
        self.assert_refused("evaluation.thresholds", 0.5, "must be a list")
        self.assert_refused("evaluation.thresholds", [0.5, "high"], r"thresholds\[1\]")

    def test_values_out_of_range_are_refused(self) -> None:
        self.assert_refused("snapshot_every", 0, "at least 1")
        self.assert_refused("max_errors_in_a_row", 0, "at least 1")
        self.assert_refused("evaluation.stage_time_limit", 0, "above 0")
        self.assert_refused("evaluation.thresholds", [float("nan")], "finite")
        self.assert_refused("sandbox.cpus", 0, "above 0")
        self.assert_refused("sandbox.max_processes", 0, "at least 1")
        self.assert_refused("prompt.max_feedback_chars", 0, "at least 1")
        self.assert_refused("parents.lambda", -1, "at least 0")
        self.assert_refused("llm.max_failures_in_a_row", 0, "at least 1")
        self.assert_refused("llm.models.0.weight", 0, "above 0")
        self.assert_refused("llm.max_tokens", 0, "at least 1")
        self.assert_refused("llm.timeout", 0, "above 0")
        self.assert_refused("llm.retries", -1, "at least 0")
        self.assert_refused("llm.temperature", 2.5, "at most 2")

    def test_lambda_may_be_zero(self) -> None:
        self.assertEqual(Problem.from_dict(changed("parents.lambda", 0)).parents.lam, 0)

    def test_unknown_parent_strategy_is_refused(self) -> None:
        self.assert_refused("parents.strategy", "openevolve", "must be one of weighted")

    def test_memory_must_be_written_as_docker_does(self) -> None:
        for memory in ("512m", "2G", "1g"):
            problem = Problem.from_dict(changed("sandbox.memory", memory))
            self.assertEqual(problem.sandbox.memory, memory)
        for memory in ("1 g", "1.5g", "1gb", "0g", "1024"):
            self.assert_refused("sandbox.memory", memory, "whole number and k, m or g")

    def test_name_must_be_usable_in_a_folder_name(self) -> None:
        self.assert_refused("name", "circle packing", "only letters, digits")
        self.assert_refused("name", "../escape", "only letters, digits")

    def test_packages_must_have_exact_versions(self) -> None:
        problem = Problem.from_dict(changed("packages", ["numpy==2.5.4", "scikit-learn==1.7.0"]))
        self.assertEqual(problem.package_names, ("numpy", "scikit-learn"))
        self.assert_refused("packages", ["numpy"], "name==version")
        self.assert_refused("packages", ["numpy>=2"], "name==version")
        self.assert_refused("packages", ["--index-url=https://example.com"], "not pip options")
        self.assert_refused("packages", ["numpy==2.5.4", "NumPy==2.5.3"], "listed twice")

    def test_entry_functions_must_be_distinct_python_names(self) -> None:
        self.assert_refused("entry_functions", [], "at least one function")
        self.assert_refused("entry_functions", ["run-search"], "not a Python name")
        self.assert_refused("entry_functions", ["class"], "not a Python name")
        self.assert_refused("entry_functions", ["run", "run"], "listed twice")


class TestModels(unittest.TestCase):
    def test_model_value_overrides_the_shared_one(self) -> None:
        data = changed("llm.timeout", 120)
        data["llm"]["models"][0]["timeout"] = 30
        self.assertEqual(first_model(data).timeout, 30)

    def test_shared_value_applies_when_the_model_sets_none(self) -> None:
        self.assertEqual(first_model(changed("llm.max_tokens", 4096)).max_tokens, 4096)

    def test_shared_address_serves_every_model(self) -> None:
        data = changed("llm.api_base", "http://localhost:11434/v1")
        del data["llm"]["models"][0]["api_base"]
        self.assertEqual(first_model(data).api_base, "http://localhost:11434/v1")

    def test_model_without_an_address_is_refused(self) -> None:
        data = minimal()
        del data["llm"]["models"][0]["api_base"]
        with self.assertRaisesRegex(ProblemError, "no api_base"):
            Problem.from_dict(data)

    def test_models_must_be_a_list_of_at_least_one(self) -> None:
        not_a_list_of_models: tuple[Any, ...] = ([], {"name": "qwen3:8b"})
        for models in not_a_list_of_models:
            with self.subTest(models=models), self.assertRaisesRegex(ProblemError, "at least one"):
                Problem.from_dict(changed("llm.models", models))

    def test_model_listed_twice_is_refused(self) -> None:
        data = minimal()
        data["llm"]["models"].append(copy.deepcopy(data["llm"]["models"][0]))
        with self.assertRaisesRegex(ProblemError, r"models\[1\]: the model 'qwen3:8b' is listed"):
            Problem.from_dict(data)

    def test_reasoning_models_are_guessed_from_their_names(self) -> None:
        for name in ("gpt-5-mini", "openai/o3", "o4-mini", "gpt-oss:20b"):
            self.assertTrue(is_reasoning_model(name), name)
        for name in ("qwen3:8b", "claude-haiku-5-5", "gpt-4o"):
            self.assertFalse(is_reasoning_model(name), name)
        self.assertTrue(first_model(changed("llm.models.0.name", "gpt-5-mini")).reasoning)

    def test_reasoning_setting_overrides_the_guess(self) -> None:
        data = changed("llm.models.0.name", "gpt-5-mini")
        data["llm"]["models"][0]["reasoning"] = False
        self.assertFalse(first_model(data).reasoning)
        self.assertTrue(first_model(changed("llm.reasoning", True)).reasoning)

    def test_reasoning_setting_must_be_true_or_false(self) -> None:
        with self.assertRaisesRegex(ProblemError, "true or false"):
            Problem.from_dict(changed("llm.reasoning", "yes please"))

    def test_reasoning_model_refuses_a_temperature(self) -> None:
        data = changed("llm.models.0.name", "o3")
        data["llm"]["temperature"] = 0.7
        with self.assertRaisesRegex(ProblemError, "refuses a temperature"):
            Problem.from_dict(data)

    def test_reasoning_effort_is_for_reasoning_models_only(self) -> None:
        data = changed("llm.models.0.name", "o3")
        data["llm"]["reasoning_effort"] = "high"
        self.assertEqual(first_model(data).reasoning_effort, "high")
        with self.assertRaisesRegex(ProblemError, "takes no reasoning_effort"):
            Problem.from_dict(changed("llm.reasoning_effort", "high"))

    def test_prices_come_in_pairs(self) -> None:
        with self.assertRaisesRegex(ProblemError, "both price_input and price_output"):
            Problem.from_dict(changed("llm.price_input", 1.0))


class TestApiKeys(unittest.TestCase):
    def test_key_is_named_by_its_environment_variable(self) -> None:
        model = first_model(changed("llm.api_key", "${ANTHROPIC_API_KEY}"))
        self.assertEqual(model.api_key_env, "ANTHROPIC_API_KEY")

    def test_key_written_in_the_file_is_refused_and_not_repeated(self) -> None:
        secret = "sk-ant-this-is-a-secret"
        with self.assertRaises(ProblemError) as caught:
            Problem.from_dict(changed("llm.models.0.api_key", secret))
        self.assertIn("${VARIABLE}", str(caught.exception))
        self.assertNotIn(secret, str(caught.exception))

    def test_badly_written_variable_is_refused(self) -> None:
        for value in ("$ANTHROPIC_API_KEY", "${1KEY}", "${A B}", 12345):
            with self.subTest(value=value), self.assertRaisesRegex(ProblemError, "VARIABLE"):
                Problem.from_dict(changed("llm.api_key", value))


class TestFingerprint(unittest.TestCase):
    def fingerprint(self, data: dict[str, Any]) -> str:
        return Problem.from_dict(data).fingerprint_without_llm()

    def test_llm_section_does_not_count(self) -> None:
        data = changed("llm.models.0.name", "qwen3-coder:30b")
        data["llm"]["max_tokens"] = 4096
        self.assertEqual(self.fingerprint(data), self.fingerprint(minimal()))

    def test_every_other_setting_counts(self) -> None:
        reference = self.fingerprint(minimal())
        for path, value in (
            ("description", "Return a small number."),
            ("evaluation.stage_time_limit", 61),
            ("sandbox.memory", "2g"),
            ("packages", ["numpy==2.5.4"]),
            ("parents.lambda", 10),
        ):
            with self.subTest(path=path):
                self.assertNotEqual(self.fingerprint(changed(path, value)), reference)

    def test_writing_a_default_does_not_count(self) -> None:
        self.assertEqual(
            self.fingerprint(changed("sandbox.memory", "1g")), self.fingerprint(minimal())
        )

    def test_same_problem_gives_the_same_fingerprint(self) -> None:
        self.assertEqual(self.fingerprint(minimal()), self.fingerprint(minimal()))


if __name__ == "__main__":
    unittest.main()
