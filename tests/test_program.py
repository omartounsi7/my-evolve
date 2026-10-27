"""Checks the run's records: Status, Result, LLMUsage and Program."""

import json
import unittest
from datetime import UTC
from typing import Any

from my_evolve.program import LLMUsage, Origin, Program, Result, Status

CODE = "def run():\n    return 1\n"
USAGE = LLMUsage(model="test-model", input_tokens=120, output_tokens=45, duration=1.5)


def ok_result(score: float = 0.5) -> Result:
    """Return a working result with a few of every optional field filled in."""
    return Result(
        status=Status.OK,
        score=score,
        metrics={"sum_radii": 0.959},
        features={"radii_spread": 0.25},
        feedback="All circles are inside the square.",
        output_data={"radii": [0.1, 0.2]},
        stage_reached=2,
        duration=3.25,
    )


def initial_program() -> Program:
    """Return an initial program with a working result."""
    return Program.initial(CODE, ok_result(), fingerprint="abc", code_complexity=12)


def child_of(parent: Program, result: Result | None = None) -> Program:
    """Return an LLM child of the parent, on island 1."""
    return Program.new_child(
        parent,
        code="def run():\n    return 2\n",
        result=result or ok_result(0.75),
        island=1,
        iteration=4,
        description="Returns two.",
        fingerprint="def",
        code_complexity=14,
        example_ids=("example-1", "example-2"),
        llm=USAGE,
    )


def strict_json(data: dict[str, Any]) -> str:
    """Write data as JSON, refusing NaN and infinities, which JSON cannot hold."""
    return json.dumps(data, allow_nan=False)


class TestStatus(unittest.TestCase):
    def test_statuses_are_saved_as_their_names(self) -> None:
        self.assertEqual(
            [status.value for status in Status],
            ["ok", "rejected", "failed", "timeout", "invalid", "error"],
        )
        self.assertEqual(Status.OK, "ok")


class TestResult(unittest.TestCase):
    def test_every_status_survives_a_round_trip(self) -> None:
        results = [ok_result()] + [
            Result.failure(status, "it broke", feedback="a hint", duration=2.0, stage_reached=1)
            for status in Status
            if status is not Status.OK
        ]
        for result in results:
            with self.subTest(status=result.status):
                data = json.loads(strict_json(result.to_dict()))
                self.assertEqual(Result.from_dict(data), result)

    def test_missing_score_is_saved_as_null(self) -> None:
        data = Result.failure(Status.FAILED, "IndexError: list index out of range").to_dict()
        self.assertIn('"score": null', strict_json(data))

    def test_only_an_ok_result_is_ok(self) -> None:
        self.assertTrue(ok_result().is_ok)
        self.assertFalse(Result.rejected("no code in the reply").is_ok)

    def test_rejected_result_keeps_its_reason(self) -> None:
        result = Result.rejected("no code in the reply")
        self.assertEqual(result.status, Status.REJECTED)
        self.assertEqual(result.error, "no code in the reply")
        self.assertIsNone(result.score)

    def test_whole_number_scores_are_stored_as_decimals(self) -> None:
        score = Result(status=Status.OK, score=1).score
        self.assertIsInstance(score, float)

    def test_ok_result_needs_a_finite_number_as_score(self) -> None:
        for score in (None, float("nan"), float("inf"), float("-inf"), True, "1.0"):
            with self.subTest(score=score), self.assertRaises(ValueError):
                Result(status=Status.OK, score=score)  # type: ignore[arg-type]

    def test_failed_result_cannot_have_a_score(self) -> None:
        with self.assertRaises(ValueError):
            Result(status=Status.FAILED, score=0.0)

    def test_failure_cannot_be_ok(self) -> None:
        with self.assertRaises(ValueError):
            Result.failure(Status.OK, "not a failure")

    def test_missing_key_is_named(self) -> None:
        data = ok_result().to_dict()
        del data["features"]
        with self.assertRaisesRegex(ValueError, "missing key 'features'"):
            Result.from_dict(data)

    def test_unknown_key_is_named(self) -> None:
        data = ok_result().to_dict()
        data["combined_score"] = 1.0
        with self.assertRaisesRegex(ValueError, "unknown key 'combined_score'"):
            Result.from_dict(data)

    def test_unknown_status_is_named(self) -> None:
        data = ok_result().to_dict()
        data["status"] = "crashed"
        with self.assertRaisesRegex(ValueError, "unknown status 'crashed'"):
            Result.from_dict(data)


class TestProgram(unittest.TestCase):
    def test_every_origin_survives_a_round_trip(self) -> None:
        initial = initial_program()
        child = child_of(initial)
        failed_child = child_of(initial, Result.failure(Status.TIMEOUT, "stage 1 ran out of time"))
        programs = [
            initial,
            child,
            failed_child,
            child.copy_to(island=2, iteration=25, mode=Origin.COPY),
            child.copy_to(island=0, iteration=50, mode=Origin.MOVE),
        ]
        for program in programs:
            with self.subTest(origin=program.origin, status=program.result.status):
                data = json.loads(strict_json(program.to_dict()))
                self.assertEqual(Program.from_dict(data), program)

    def test_a_program_is_one_json_line(self) -> None:
        line = strict_json(child_of(initial_program()).to_dict())
        self.assertNotIn("\n", line)

    def test_initial_program_starts_everything(self) -> None:
        initial = initial_program()
        self.assertEqual(initial.origin, Origin.INITIAL)
        self.assertIsNone(initial.parent_id)
        self.assertIsNone(initial.island)
        self.assertEqual((initial.iteration, initial.generation), (0, 0))
        self.assertIsNone(initial.llm)
        self.assertEqual(initial.created_at.tzinfo, UTC)

    def test_child_is_one_generation_after_its_parent(self) -> None:
        parent = initial_program()
        child = child_of(child_of(parent))
        self.assertEqual(child.origin, Origin.LLM)
        self.assertEqual(child.generation, 2)
        self.assertNotEqual(child.id, parent.id)

    def test_child_remembers_its_parent_and_its_call(self) -> None:
        parent = initial_program()
        child = child_of(parent)
        self.assertEqual(child.parent_id, parent.id)
        self.assertEqual(child.llm, USAGE)
        self.assertEqual(child.example_ids, ("example-1", "example-2"))

    def test_copy_keeps_the_program_but_not_its_call(self) -> None:
        original = child_of(initial_program())
        for mode in (Origin.COPY, Origin.MOVE):
            with self.subTest(mode=mode):
                copy = original.copy_to(island=2, iteration=25, mode=mode)
                self.assertEqual(copy.origin, mode)
                self.assertNotEqual(copy.id, original.id)
                self.assertEqual(copy.parent_id, original.id)
                self.assertEqual((copy.island, copy.iteration), (2, 25))
                self.assertEqual(copy.generation, original.generation)
                self.assertEqual(copy.code, original.code)
                self.assertEqual(copy.result, original.result)
                self.assertEqual(copy.fingerprint, original.fingerprint)
                self.assertEqual(copy.code_complexity, original.code_complexity)
                self.assertEqual(copy.description, original.description)
                self.assertIsNone(copy.llm)
                self.assertEqual(copy.example_ids, ())

    def test_copy_must_be_a_copy_or_a_move(self) -> None:
        for mode in (Origin.INITIAL, Origin.LLM):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                initial_program().copy_to(island=0, iteration=0, mode=mode)

    def test_summary_leaves_out_the_code(self) -> None:
        summary = repr(initial_program())
        self.assertIn("status=ok", summary)
        self.assertNotIn("def run", summary)

    def test_missing_key_is_named(self) -> None:
        data = initial_program().to_dict()
        del data["fingerprint"]
        with self.assertRaisesRegex(ValueError, "missing key 'fingerprint'"):
            Program.from_dict(data)

    def test_unknown_key_is_named(self) -> None:
        data = initial_program().to_dict()
        data["metadata"] = {}
        with self.assertRaisesRegex(ValueError, "unknown key 'metadata'"):
            Program.from_dict(data)

    def test_nested_missing_key_says_where_it_is(self) -> None:
        data = child_of(initial_program()).to_dict()
        del data["llm"]["model"]
        with self.assertRaisesRegex(ValueError, r"program\.llm: missing key 'model'"):
            Program.from_dict(data)

    def test_unknown_status_inside_a_program_is_named(self) -> None:
        data = initial_program().to_dict()
        data["result"]["status"] = "crashed"
        with self.assertRaisesRegex(ValueError, r"program\.result: unknown status 'crashed'"):
            Program.from_dict(data)

    def test_unknown_origin_is_named(self) -> None:
        data = initial_program().to_dict()
        data["origin"] = "mutation"
        with self.assertRaisesRegex(ValueError, "unknown origin 'mutation'"):
            Program.from_dict(data)

    def test_time_without_a_time_zone_is_refused(self) -> None:
        data = initial_program().to_dict()
        data["created_at"] = "2026-10-26T19:04:05"
        with self.assertRaisesRegex(ValueError, "time zone"):
            Program.from_dict(data)


if __name__ == "__main__":
    unittest.main()
