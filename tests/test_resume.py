"""Checks continuing a run: the same command finishes it; a changed problem is refused.

Each test first runs the loop tests' tiny problem, then runs it again on the same
folder, the way a user continues a run after a crash or with a larger --iterations.
Each run has its own fake LLM server, so the llm section's address changes between
sessions, which is allowed.
"""

from pathlib import Path

from test_loop import LoopTestCase, reply_with

from my_evolve.loop import RunError, run_generator
from my_evolve.program import Origin

REPLIES = [reply_with(str(n)) for n in range(2, 12)]


class TestContinuing(LoopTestCase):
    def test_running_again_extends_the_run_to_the_new_total(self) -> None:
        self.run_with(REPLIES, iterations=3)
        self.run_with(REPLIES, iterations=5)
        self.assertNotIn("Evaluating the initial program", self.console)
        self.assertIn("Continuing the run", self.console)
        self.assertIn("3 iterations completed, 5 programs saved", self.console)
        self.assertEqual([row.iteration for row in self.storage.load_history()], [1, 2, 3, 4, 5])
        programs = self.storage.load_programs()
        # The initial program was not evaluated nor stored again.
        self.assertEqual([p.origin for p in programs].count(Origin.INITIAL), 1)
        self.assertEqual([p.origin for p in programs].count(Origin.COPY), 1)
        info = self.storage.read_run_info()
        assert info is not None
        self.assertEqual(len(info.sessions), 2)
        self.assertEqual(info.sessions[-1].end, "5 iterations completed")

    def test_same_total_again_has_nothing_to_do(self) -> None:
        self.run_with(REPLIES, iterations=3)
        self.run_with(REPLIES, iterations=3)
        # Only the start-up check of the models was sent.
        self.assertEqual(len(self.server.requests), 1)
        self.assertIn("nothing more to do", self.console)
        self.assertEqual(len(self.storage.load_history()), 3)

    def test_continued_run_builds_on_the_saved_programs(self) -> None:
        self.run_with([reply_with("9")], iterations=1)
        self.run_with([reply_with("4")], iterations=2)
        # The prompt of the new session shows the best program saved before it.
        prompt = self.server.bodies[1]["messages"][1]["content"]
        self.assertIn("best score so far in this run: 9", prompt)
        programs = self.storage.load_programs()
        ids = {program.id for program in programs}
        self.assertTrue(all(program.parent_id in ids for program in programs[1:]))

    def test_draws_go_on_instead_of_repeating(self) -> None:
        fresh = [run_generator(7, 0).random() for _ in range(5)]
        resumed = [run_generator(7, 12).random() for _ in range(5)]
        self.assertNotEqual(fresh, resumed)
        self.assertEqual(resumed, [run_generator(7, 12).random() for _ in range(5)])

    def test_a_continued_run_keeps_its_seed(self) -> None:
        self.run_with(REPLIES, iterations=1, seed=5)
        self.run_with(REPLIES, iterations=2, seed=99)
        self.assertIn("--seed 99 is ignored: a continued run keeps its seed, 5.", self.console)
        info = self.storage.read_run_info()
        assert info is not None
        self.assertEqual(info.seed, 5)


class TestAfterACrash(LoopTestCase):
    def remove_line(self, path: Path, index: int) -> None:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        del lines[index]
        path.write_text("".join(lines), encoding="utf-8")

    def test_child_saved_without_its_history_row_is_dropped(self) -> None:
        self.run_with([reply_with("2"), reply_with("50")], iterations=2)
        # A crash after the second child was saved, before its history row.
        self.remove_line(self.storage.history_path, -1)
        dropped = self.storage.load_programs()[-1]
        self.run_with([reply_with("3")], iterations=2)
        self.assertIn("Dropped the child of iteration 2", self.console)
        programs = self.storage.load_programs()
        self.assertNotIn(dropped.id, {program.id for program in programs})
        self.assertEqual([row.iteration for row in self.storage.load_history()], [1, 2])
        self.assertEqual([call.iteration for call in self.storage.load_llm_calls()], [1, 2])
        # The dropped child was the best: best_program.py no longer shows it.
        self.assertNotIn(dropped.id, self.storage.best_path.read_text(encoding="utf-8"))

    def test_iteration_numbers_lost_by_a_crash_are_not_reused(self) -> None:
        self.run_with(REPLIES, iterations=3)
        # Iteration 2 was in flight when the run crashed (with several workers).
        self.remove_line(self.storage.history_path, 2)
        self.run_with(REPLIES, iterations=3)
        self.assertEqual([row.iteration for row in self.storage.load_history()], [1, 3, 4])

    def test_cut_off_last_line_is_dropped(self) -> None:
        self.run_with(REPLIES, iterations=2)
        with self.storage.programs_path.open("a", encoding="utf-8") as file:
            file.write('{"id": "cut-off')
        self.run_with(REPLIES, iterations=3)
        self.assertEqual(len(self.storage.load_history()), 3)

    def test_island_left_without_its_copy_gets_it(self) -> None:
        self.run_with(REPLIES, iterations=1)
        # A crash right after the initial program was stored, before anything else.
        initial = self.storage.load_programs()[0]
        self.storage.rewrite_programs([initial])
        self.storage.history_path.unlink()
        self.storage.llm_calls_path.unlink()
        self.run_with(REPLIES, iterations=1)
        origins = [program.origin for program in self.storage.load_programs()]
        self.assertEqual(origins, [Origin.INITIAL, Origin.COPY, Origin.LLM])

    def test_programs_without_run_information_are_refused(self) -> None:
        self.run_with(REPLIES, iterations=1)
        self.storage.run_info_path.unlink()
        with self.assertRaisesRegex(RunError, "no run.json"):
            self.run_with(REPLIES, iterations=2)


class TestRefusals(LoopTestCase):
    def test_a_changed_problem_cannot_be_continued(self) -> None:
        cases = {
            "evaluation.py": "the evaluation file",
            "initial_program.py": "the initial program",
        }
        for number, (file_name, message) in enumerate(cases.items()):
            with self.subTest(file_name=file_name):
                output = self.folder / f"run{number}"
                self.run_with(REPLIES, iterations=1, output=output)
                path = self.folder / file_name
                original = path.read_text(encoding="utf-8")
                path.write_text(original + "\n# changed\n", encoding="utf-8")
                try:
                    with self.assertRaisesRegex(RunError, f"{message} changed since it started"):
                        self.run_with(REPLIES, iterations=2, output=output)
                finally:
                    path.write_text(original, encoding="utf-8")

    def test_a_changed_problem_setting_cannot_be_continued(self) -> None:
        self.run_with(REPLIES, iterations=1)
        with self.assertRaisesRegex(RunError, "the problem file"):
            self.run_with(REPLIES, iterations=2, problem={"snapshot_every": 3})

    def test_llm_section_and_written_out_defaults_may_change(self) -> None:
        # The second run's server has another address; 3 is max_errors_in_a_row's default.
        self.run_with(REPLIES, iterations=1)
        self.run_with(REPLIES, iterations=2, problem={"max_errors_in_a_row": 3})
        self.assertEqual(len(self.storage.load_history()), 2)
