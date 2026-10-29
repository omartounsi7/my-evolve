"""Checks the records of a run: Result and Program."""

import json
import unittest

from my_evolve.program import Program, Result


class ResultTest(unittest.TestCase):
    def test_a_failed_result_has_no_score(self) -> None:
        """A failed program's score is written null in JSON, never -Infinity."""
        line = json.dumps(Result(error="ValueError: bad").to_dict(), allow_nan=False)
        self.assertEqual(json.loads(line), {"score": None, "error": "ValueError: bad"})


class ProgramTest(unittest.TestCase):
    def test_the_initial_program(self) -> None:
        """A program made without a parent is generation 0, iteration 0, with a fresh id."""
        program = Program("x = 1\n", Result(score=1.0))
        self.assertIsNone(program.parent_id)
        self.assertEqual((program.generation, program.iteration), (0, 0))
        self.assertNotEqual(program.id, Program("x = 1\n", Result(score=1.0)).id)

    def test_a_child_descends_from_its_parent(self) -> None:
        """new_child links the child to its parent, one generation further."""
        parent = Program("x = 1\n", Result(score=1.0))
        child = Program.new_child(parent, "x = 2\n", Result(score=2.0), iteration=7)
        grandchild = Program.new_child(child, "x = 3\n", Result(score=3.0), iteration=9)
        self.assertEqual(child.parent_id, parent.id)
        self.assertEqual((child.generation, child.iteration), (1, 7))
        self.assertEqual((grandchild.parent_id, grandchild.generation), (child.id, 2))

    def test_to_dict_gives_plain_json_values(self) -> None:
        """A program written as JSON and read back gives the same values."""
        program = Program("x = 1\n", Result(score=0.5))
        data = program.to_dict()
        self.assertEqual(json.loads(json.dumps(data, allow_nan=False)), data)
        self.assertEqual(data["id"], program.id)
        self.assertEqual(data["result"], {"score": 0.5, "error": None})
        self.assertEqual(data["code"], "x = 1\n")


if __name__ == "__main__":
    unittest.main()
