"""Checks that problem files are read, and every mistake in them reported clearly."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from typing import Any

from my_evolve.problem import FeatureSpec, Problem, ProblemError

REPOSITORY_FOLDER = Path(__file__).parent.parent


def valid_data() -> dict[str, Any]:
    """Return the parsed content of a correct problem file."""
    return {
        "name": "toy",
        "description": "Return a number.",
        "entry_functions": ["solve"],
        "llm": {"api_base": "http://localhost:11434/v1", "models": [{"name": "some-model"}]},
    }


class ProblemTest(unittest.TestCase):
    def test_a_correct_problem(self) -> None:
        """Every value of a correct file reaches the Problem."""
        problem = Problem.from_dict(valid_data())
        self.assertEqual(problem.name, "toy")
        self.assertEqual(problem.description, "Return a number.")
        self.assertEqual(problem.llm.models[0].name, "some-model")
        self.assertEqual(problem.llm.models[0].api_base, "http://localhost:11434/v1")

    def test_the_example_problem_files_load(self) -> None:
        """The repository's problem files are correct."""
        for path in [
            REPOSITORY_FOLDER / "examples" / "circle_packing" / "problem.yaml",
            Path(__file__).parent / "toy" / "problem.yaml",
        ]:
            with self.subTest(path=path.name):
                self.assertTrue(Problem.load(path).description)

    def test_an_unknown_key_is_refused_with_its_location(self) -> None:
        """A misspelt key is an error, not silently ignored."""
        data = valid_data()
        data["descripton"] = "typo"
        with self.assertRaisesRegex(ProblemError, "unknown key 'descripton' in the problem file"):
            Problem.from_dict(data)
        data = valid_data()
        data["llm"]["temprature"] = 0.7
        with self.assertRaisesRegex(ProblemError, "unknown key 'temprature' in the llm section"):
            Problem.from_dict(data)

    def test_the_model_settings_and_their_defaults(self) -> None:
        """Unset settings are None (not sent); max_tokens, timeout and retries have defaults."""
        model = Problem.from_dict(valid_data()).llm.models[0]
        self.assertEqual(
            (model.api_key_env, model.temperature, model.reasoning_effort, model.reasoning),
            (None, None, None, False),
        )
        self.assertEqual((model.max_tokens, model.timeout, model.retries), (16_384, 300.0, 2))
        self.assertEqual(
            (model.weight, Problem.from_dict(valid_data()).llm.max_failures_in_a_row), (1.0, 3)
        )

    def test_shared_values_and_a_models_own(self) -> None:
        """The section's values apply to every model; a model's own value wins."""
        data = valid_data()
        data["llm"].update(api_key="${MY_KEY}", temperature=0.7, max_failures_in_a_row=5)
        data["llm"]["models"] = [
            {"name": "a", "weight": 0.8},
            {"name": "b", "weight": 0.2, "temperature": 0.1, "api_base": "http://other/v1"},
        ]
        llm = Problem.from_dict(data).llm
        first, second = llm.models
        self.assertEqual((first.temperature, second.temperature), (0.7, 0.1))
        self.assertEqual((first.api_key_env, second.api_key_env), ("MY_KEY", "MY_KEY"))
        self.assertEqual(
            (first.api_base, second.api_base), ("http://localhost:11434/v1", "http://other/v1")
        )
        self.assertEqual(
            ([first.weight, second.weight], llm.max_failures_in_a_row), ([0.8, 0.2], 5)
        )

    def test_wrong_ensembles_are_refused(self) -> None:
        for models, error in [
            ([], "a list of one model or more"),
            ([{"name": "a"}, {"name": "a"}], "the same name"),
            ([{"name": "a", "weight": 0}], "'weight' .* above 0"),
            ([{"name": "a", "colour": "red"}], "unknown key 'colour' in model 1"),
            ([{"weight": 1}], "missing key 'name' in model 1"),
        ]:
            data = valid_data()
            data["llm"]["models"] = models
            with self.subTest(error=error), self.assertRaisesRegex(ProblemError, error):
                Problem.from_dict(data)
        data = valid_data()
        del data["llm"]["api_base"]
        with self.assertRaisesRegex(ProblemError, "missing key 'api_base'"):
            Problem.from_dict(data)

    def test_a_key_written_in_the_file_is_refused(self) -> None:
        """Only ${VARIABLE}: problem files can be shared without leaking a key."""
        for key in ["sk-ant-123", "$MY_KEY", "${}", 3]:
            data = valid_data()
            data["llm"]["api_key"] = key
            with self.subTest(key=key), self.assertRaisesRegex(ProblemError, "never write"):
                Problem.from_dict(data)

    def test_reasoning_models(self) -> None:
        """Guessed from the name, without a provider prefix; they refuse a temperature."""
        for name, reasoning in [
            ("o3-mini", True),
            ("openai/gpt-5-mini", True),
            ("gpt-oss:20b", True),
            ("gpt-4o", False),
            ("qwen3-coder:30b", False),
        ]:
            data = valid_data()
            data["llm"]["models"] = [{"name": name}]
            with self.subTest(name=name):
                self.assertEqual(Problem.from_dict(data).llm.models[0].reasoning, reasoning)
        data = valid_data()
        data["llm"]["models"] = [{"name": "o4-mini", "temperature": 0.5}]
        with self.assertRaisesRegex(ProblemError, "reasoning model, which refuses a temperature"):
            Problem.from_dict(data)
        data["llm"]["models"] = [{"name": "qwen3:8b", "reasoning_effort": "high"}]
        with self.assertRaisesRegex(ProblemError, "for reasoning models only"):
            Problem.from_dict(data)
        data["llm"]["models"][0]["reasoning"] = True
        self.assertEqual(Problem.from_dict(data).llm.models[0].reasoning_effort, "high")

    def test_the_example_problem_files_for_claude(self) -> None:
        """problem_claude.yaml differs only in its llm section: Appendix B's two batches."""
        for name in ("circle_packing", "function_minimization"):
            folder = REPOSITORY_FOLDER / "examples" / name
            with self.subTest(name=name):
                local = Problem.load(folder / "problem.yaml")
                claude = Problem.load(folder / "problem_claude.yaml")
                self.assertEqual(
                    [(model.name, model.weight) for model in local.llm.models],
                    [("qwen3-coder:30b", 0.8), ("qwen3:8b", 0.2)],
                )
                self.assertEqual(
                    [(model.name, model.weight) for model in claude.llm.models],
                    [("claude-haiku-5-5", 0.8), ("claude-sonnet-5-5", 0.2)],
                )
                self.assertEqual(claude.llm.models[0].api_key_env, "ANTHROPIC_API_KEY")
                self.assertEqual(replace(claude, llm=local.llm), local)

    def test_entry_functions(self) -> None:
        """Required: a list of one or more function names."""
        self.assertEqual(Problem.from_dict(valid_data()).entry_functions, ("solve",))
        for wrong in [[], "solve", ["solve()"], ["two words"], [3]]:
            data = valid_data()
            data["entry_functions"] = wrong
            with self.subTest(value=wrong), self.assertRaisesRegex(ProblemError, "function names"):
                Problem.from_dict(data)

    def test_the_stage_time_limit(self) -> None:
        """60 s by default; any number above 0 may be set."""
        self.assertEqual(Problem.from_dict(valid_data()).evaluation.stage_time_limit, 60.0)
        data = valid_data()
        data["evaluation"] = {"stage_time_limit": 5}
        self.assertEqual(Problem.from_dict(data).evaluation.stage_time_limit, 5.0)
        for wrong in [0, -1, "60", True]:
            data["evaluation"] = {"stage_time_limit": wrong}
            with self.subTest(value=wrong), self.assertRaisesRegex(ProblemError, "above 0"):
                Problem.from_dict(data)
        data["evaluation"] = {"thresholds": [0.5, 1]}
        self.assertEqual(Problem.from_dict(data).evaluation.thresholds, (0.5, 1.0))
        data["evaluation"] = {"thresholds": [0.5, "high"]}
        with self.assertRaisesRegex(ProblemError, "list of numbers"):
            Problem.from_dict(data)
        data["evaluation"] = {"time_limit": 5}
        with self.assertRaisesRegex(ProblemError, "unknown key 'time_limit' in the evaluation"):
            Problem.from_dict(data)

    def test_the_prompt_and_sandbox_sections(self) -> None:
        """Their defaults, and values that are refused."""
        problem = Problem.from_dict(valid_data())
        self.assertEqual(
            (
                problem.prompt.example_programs,
                problem.prompt.max_chars,
                problem.prompt.max_feedback_chars,
            ),
            (2, 60_000, 2000),
        )
        self.assertEqual(
            (problem.sandbox.memory, problem.sandbox.cpus, problem.sandbox.max_processes),
            ("1g", 1.0, 64),
        )
        data = valid_data()
        data["prompt"] = {"max_feedback_chars": 500, "example_programs": 0}
        data["sandbox"] = {"memory": "512m", "cpus": 2, "max_processes": 32}
        problem = Problem.from_dict(data)
        self.assertEqual(problem.prompt.max_feedback_chars, 500)
        self.assertEqual(problem.sandbox.memory, "512m")
        for section, wrong in [
            ("prompt", {"max_feedback_chars": 0}),
            ("prompt", {"example_programs": -1}),
            ("prompt", {"max_chars": 0}),
            ("sandbox", {"memory": "lots"}),
            ("sandbox", {"cpus": -1}),
            ("sandbox", {"max_processes": 1.5}),
            ("sandbox", {"network": "none"}),
        ]:
            data = valid_data()
            data[section] = wrong
            with self.subTest(section=section, value=wrong), self.assertRaises(ProblemError):
                Problem.from_dict(data)

    def test_the_grid_section(self) -> None:
        """code_complexity from -1 to 3 in 10 bins by default (D18)."""
        default = (FeatureSpec("code_complexity", -1.0, 3.0, 10),)
        self.assertEqual(Problem.from_dict(valid_data()).grid_features, default)
        data = valid_data()
        data["grid"] = {"features": [{"name": "code_complexity", "low": 0, "high": 2}]}
        self.assertEqual(
            Problem.from_dict(data).grid_features, (FeatureSpec("code_complexity", 0, 2, 10),)
        )
        for features, error in [
            ([{"name": "code_complexity", "low": 2, "high": 2}], "'low' must be below 'high'"),
            ([{"name": "code_complexity", "low": 0, "high": "3"}], "'high' .* must be a number"),
            ([{"name": "code_complexity", "low": 0, "high": 1, "bins": 0}], "'bins'"),
            ([{"name": "code_complexity", "low": 0}], "missing key 'high'"),
            ([], "1 to 3 features"),
            ([{"name": f"f{n}", "low": 0, "high": 1} for n in range(4)], "1 to 3 features"),
            ([{"name": "a", "low": 0, "high": 1}, {"name": "a", "low": 0, "high": 2}], "same name"),
        ]:
            data["grid"] = {"features": features}
            with self.subTest(error=error), self.assertRaisesRegex(ProblemError, error):
                Problem.from_dict(data)

    def test_output_features_and_default_bins(self) -> None:
        """Any other name is an output feature; 5 bins each for 2 features, 3 for 3."""
        data = valid_data()
        data["grid"] = {
            "features": [
                {"name": "code_complexity", "low": -1, "high": 3},
                {"name": "radii_spread", "low": 0, "high": 1},
            ]
        }
        problem = Problem.from_dict(data)
        self.assertEqual([feature.bins for feature in problem.grid_features], [5, 5])
        self.assertEqual(problem.output_feature_names, ("radii_spread",))
        data["grid"]["features"].append({"name": "c", "low": -1, "high": 1, "bins": 4})
        problem = Problem.from_dict(data)
        self.assertEqual([feature.bins for feature in problem.grid_features], [3, 3, 4])
        self.assertEqual(problem.output_feature_names, ("radii_spread", "c"))
        self.assertEqual(Problem.from_dict(valid_data()).output_feature_names, ())

    def test_the_islands_section(self) -> None:
        islands = Problem.from_dict(valid_data()).islands
        self.assertEqual(
            (islands.count, islands.migration_interval, islands.migration_share),
            (3, 25, 0.1),
        )
        self.assertEqual(
            (islands.migrants, islands.destinations, islands.mode),
            ("random_non_best", "all_others", "copy"),
        )
        for wrong, error in [
            ({"migration_share": 1.5}, "at most 1"),
            ({"migration_share": 0}, "above 0"),
            ({"migrants": "worst"}, "must be one of random_non_best, best, random"),
            ({"destinations": "nearest"}, "must be one of all_others, ring"),
            ({"mode": "swap"}, "must be one of copy, move"),
            ({"migration_interval": 0}, "'migration_interval'"),
        ]:
            data = valid_data()
            data["islands"] = wrong
            with self.subTest(value=wrong), self.assertRaisesRegex(ProblemError, error):
                Problem.from_dict(data)
        data = valid_data()
        data["islands"] = {"count": 0}
        with self.assertRaisesRegex(ProblemError, "'count' in the islands section"):
            Problem.from_dict(data)

    def test_the_parents_section(self) -> None:
        """The weighted rule with lambda 1 by default; unknown strategies are refused."""
        parents = Problem.from_dict(valid_data()).parents
        self.assertEqual((parents.strategy, parents.lam), ("weighted", 1.0))
        data = valid_data()
        data["parents"] = {"lambda": 10}
        self.assertEqual(Problem.from_dict(data).parents.lam, 10.0)
        self.assertEqual(parents.archive_size, 10)
        data["parents"] = {"strategy": "openevolve", "archive_size": 5}
        parents = Problem.from_dict(data).parents
        self.assertEqual((parents.strategy, parents.archive_size), ("openevolve", 5))
        for wrong, error in [
            ({"strategy": "best"}, "must be one of weighted, openevolve"),
            ({"lambda": 0}, "above 0"),
            ({"archive_size": 0}, "'archive_size'"),
        ]:
            data["parents"] = wrong
            with self.subTest(value=wrong), self.assertRaisesRegex(ProblemError, error):
                Problem.from_dict(data)

    def test_packages_need_exact_versions(self) -> None:
        """Only name==version entries: no ranges, no pip options, no duplicates."""
        data = valid_data()
        self.assertEqual(Problem.from_dict(data).packages, ())
        data["packages"] = ["numpy==2.5.4", "scikit-learn==1.8.0"]
        self.assertEqual(Problem.from_dict(data).packages, ("numpy==2.5.4", "scikit-learn==1.8.0"))
        for wrong in [["numpy"], ["numpy>=2"], ["--index-url=http://x"], ["-e ."], [3], "numpy"]:
            data["packages"] = wrong
            with self.subTest(packages=wrong), self.assertRaises(ProblemError):
                Problem.from_dict(data)
        data["packages"] = ["numpy==2.5.4", "NumPy==2.5.3"]
        with self.assertRaisesRegex(ProblemError, "listed twice"):
            Problem.from_dict(data)

    def test_a_missing_key_is_refused(self) -> None:
        """Each required key must be there."""
        data = valid_data()
        del data["llm"]["models"]
        with self.assertRaisesRegex(ProblemError, "missing key 'models' in the llm section"):
            Problem.from_dict(data)

    def test_values_must_be_text(self) -> None:
        """An empty description, or a section that is not a mapping, is refused."""
        data = valid_data()
        data["description"] = "  "
        with self.assertRaisesRegex(ProblemError, "'description' .* must be some text"):
            Problem.from_dict(data)
        data = valid_data()
        data["llm"] = "qwen3-coder:30b"
        with self.assertRaisesRegex(ProblemError, "the llm section must be a mapping"):
            Problem.from_dict(data)

    def test_errors_name_the_file(self) -> None:
        """Errors from load name the file; a file that is not a mapping is refused."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "problem.yaml"
            path.write_text("- just\n- a list\n", encoding="utf-8")
            with self.assertRaisesRegex(ProblemError, "problem.yaml: the problem file must be"):
                Problem.load(path)
            with self.assertRaisesRegex(ProblemError, "cannot be read"):
                Problem.load(Path(folder) / "missing.yaml")


if __name__ == "__main__":
    unittest.main()
