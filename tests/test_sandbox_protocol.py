"""Checks that values survive the trip between host and worker, and that others are refused."""

import io
import json
import math
import unittest
from typing import Any

import numpy as np

from my_evolve.sandbox_protocol import (
    NotPlainData,
    ProtocolError,
    decode,
    encode,
    receive,
    send,
)


def round_trip(value: Any) -> Any:
    """Encode a value, write it as JSON as the protocol does, read it back and decode it."""
    line = json.dumps(encode(value), allow_nan=False)
    return decode(json.loads(line))


class TestPlainValues(unittest.TestCase):
    def test_simple_values_come_back_unchanged(self) -> None:
        for value in (None, True, False, 0, -7, 2**70, 1.5, -0.25, "", "text", "été ✓"):
            with self.subTest(value=value):
                result = round_trip(value)
                self.assertEqual(result, value)
                self.assertIs(type(result), type(value))

    def test_floats_json_cannot_hold_come_back(self) -> None:
        self.assertTrue(math.isnan(round_trip(math.nan)))
        self.assertEqual(round_trip(math.inf), math.inf)
        self.assertEqual(round_trip(-math.inf), -math.inf)

    def test_tuples_stay_tuples_even_inside_lists(self) -> None:
        value = [(1.0, 2.0, -1.5), [(3, (4, "five"))], ()]
        result = round_trip(value)
        self.assertEqual(result, value)
        self.assertIsInstance(result[0], tuple)
        self.assertIsInstance(result[1][0][1], tuple)

    def test_dictionaries_with_text_keys_come_back(self) -> None:
        value = {"centres": [(0.1, 0.2)], "nested": {"__tuple__": 1}, "": None}
        self.assertEqual(round_trip(value), value)

    def test_dictionary_with_other_keys_is_refused(self) -> None:
        with self.assertRaisesRegex(NotPlainData, "keys must be text"):
            encode({1: "one"})

    def test_other_types_are_refused(self) -> None:
        for value in ({1, 2}, b"bytes", object(), print, 1 + 2j, range(3)):
            with self.subTest(value=value), self.assertRaises(NotPlainData):
                encode(value)

    def test_refusal_inside_a_container_is_reported(self) -> None:
        with self.assertRaises(NotPlainData):
            encode([1, 2, {3}])


class TestArrays(unittest.TestCase):
    def assert_same_array(self, array: Any) -> None:
        result = round_trip(array)
        self.assertIsInstance(result, np.ndarray)
        self.assertEqual(result.dtype, array.dtype)
        self.assertEqual(result.shape, array.shape)
        np.testing.assert_array_equal(result, array)

    def test_arrays_of_numbers_of_any_shape_come_back(self) -> None:
        for array in (
            np.zeros((26, 2)),
            np.arange(26, dtype=np.int64),
            np.linspace(0, 1, 5, dtype=np.float32),
            np.array([True, False]),
            np.array(3.5),
            np.zeros((0, 3), dtype=np.uint8),
            np.array([np.nan, np.inf, -1.0]),
        ):
            with self.subTest(dtype=array.dtype, shape=array.shape):
                self.assert_same_array(array)

    def test_array_that_is_not_contiguous_comes_back(self) -> None:
        self.assert_same_array(np.arange(12.0).reshape(3, 4).T)

    def test_decoded_array_can_be_changed(self) -> None:
        result = round_trip(np.zeros(3))
        result[0] = 1.0
        self.assertEqual(result[0], 1.0)

    def test_arrays_inside_tuples_come_back(self) -> None:
        centres, radii, total = round_trip((np.zeros((26, 2)), np.full(26, 0.1), 2.6))
        self.assertEqual(centres.shape, (26, 2))
        self.assertEqual(radii.shape, (26,))
        self.assertEqual(total, 2.6)

    def test_numpy_numbers_become_python_numbers(self) -> None:
        for value, expected in ((np.float64(2.5), 2.5), (np.int32(7), 7), (np.bool_(True), True)):
            with self.subTest(value=value):
                result = round_trip(value)
                self.assertEqual(result, expected)
                self.assertIs(type(result), type(expected))
        self.assertTrue(math.isnan(round_trip(np.float64("nan"))))

    def test_arrays_of_other_things_are_refused(self) -> None:
        for array in (np.array(["a", "b"]), np.array([object()]), np.array([1 + 2j])):
            with self.subTest(dtype=array.dtype), self.assertRaises(NotPlainData):
                encode(array)

    def test_object_array_cannot_be_smuggled_in_by_the_sender(self) -> None:
        forged = {"__ndarray__": {"dtype": "|O", "shape": [1], "data": "AAAAAAAAAAA="}}
        with self.assertRaises(ProtocolError):
            decode(forged)


class TestDecode(unittest.TestCase):
    def test_unknown_tag_is_refused(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "unknown tag"):
            decode({"__set__": [1, 2]})

    def test_untagged_dictionary_is_refused(self) -> None:
        with self.assertRaisesRegex(ProtocolError, "tagged"):
            decode({"a": 1, "b": 2})

    def test_unknown_float_is_refused(self) -> None:
        with self.assertRaises(ProtocolError):
            decode({"__float__": "huge"})


class TestMessages(unittest.TestCase):
    def test_messages_are_one_line_each_and_come_back_in_order(self) -> None:
        stream = io.StringIO()
        send(stream, {"type": "load", "code": "x = 1\nprint('two lines')\n"})
        send(stream, {"type": "call", "id": 1, "name": "f", "args": [], "kwargs": encode({})})
        self.assertEqual(stream.getvalue().count("\n"), 2)
        stream.seek(0)
        self.assertEqual(receive(stream), {"type": "load", "code": "x = 1\nprint('two lines')\n"})
        self.assertEqual(receive(stream)["id"], 1)  # type: ignore[index]
        self.assertIsNone(receive(stream))

    def test_lines_are_written_in_ascii(self) -> None:
        stream = io.StringIO()
        send(stream, {"type": "load", "code": "s = 'été'\n"})
        self.assertTrue(stream.getvalue().isascii())

    def test_line_that_is_not_a_message_is_refused(self) -> None:
        for line in ("not json\n", "[1, 2]\n", '{"id": 1}\n'):
            with self.subTest(line=line), self.assertRaises(ProtocolError):
                receive(io.StringIO(line))


if __name__ == "__main__":
    unittest.main()
