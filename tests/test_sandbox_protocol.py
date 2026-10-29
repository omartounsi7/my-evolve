"""Checks that values travel between host and worker exactly, and that others are refused."""

import json
import math
import unittest
from typing import Any

import numpy as np

from my_evolve.sandbox_protocol import NotPlainData, decode, encode


def round_trip(value: Any) -> Any:
    """Encode a value, write it as JSON and read it back, as a message would carry it."""
    return decode(json.loads(json.dumps(encode(value), allow_nan=False)))


class RoundTripTest(unittest.TestCase):
    def test_plain_values_come_back_unchanged(self) -> None:
        """Numbers, text, None, lists, tuples (nested too) and dicts keep their types."""
        for value in [
            None,
            True,
            3,
            2**70,
            1.5,
            "é and ≈",
            [1, [2, 3]],
            (1, (2.5, "x")),
            [(1, 2), (3, 4)],
            {"a": (1, 2), "b": {"c": [None]}},
            {"__tuple__": [1]},
            (),
        ]:
            with self.subTest(value=value):
                back = round_trip(value)
                self.assertEqual(back, value)
                self.assertEqual(type(back), type(value))

    def test_non_finite_floats(self) -> None:
        """nan, inf and -inf, which JSON cannot write, travel too."""
        self.assertTrue(math.isnan(round_trip(float("nan"))))
        self.assertEqual(round_trip([float("inf"), -math.inf]), [math.inf, -math.inf])

    def test_numpy_arrays_keep_their_type_and_shape(self) -> None:
        """Arrays of numbers of any type and shape, non-contiguous ones included."""
        arrays: list[np.ndarray[Any, Any]] = [
            np.arange(6, dtype=np.int64).reshape(2, 3),
            np.linspace(0, 1, 24, dtype=np.float32).reshape(2, 3, 4),
            np.array([True, False]),
            np.zeros((0, 3)),
            np.arange(12.0).reshape(3, 4).T,
            np.array([1 + 2j]),
            np.array(7.5),
        ]
        for array in arrays:
            with self.subTest(dtype=str(array.dtype), shape=array.shape):
                back = round_trip(array)
                self.assertIsInstance(back, np.ndarray)
                self.assertEqual((back.dtype, back.shape), (array.dtype, array.shape))
                np.testing.assert_array_equal(back, array)
                back[...] = 0  # writable

    def test_numpy_numbers_become_python_numbers(self) -> None:
        """A numpy number comes back as the Python number of the same value."""
        self.assertEqual(round_trip((np.float64(0.5), np.int32(3), np.bool_(True))), (0.5, 3, True))
        self.assertIs(type(round_trip(np.int64(3))), int)


class RefusalTest(unittest.TestCase):
    def test_values_that_are_not_plain_data_are_refused(self) -> None:
        """Objects, functions, sets, non-text keys and arrays of anything but numbers."""
        for value in [
            object(),
            print,
            {1, 2},
            {1: "one"},
            np.array(["text"]),
            np.array([object()], dtype=object),
        ]:
            with self.subTest(value=repr(value)), self.assertRaises(NotPlainData):
                encode(value)

    def test_malformed_data_is_refused(self) -> None:
        """decode accepts only what encode writes: never pickle, never object arrays."""
        object_array = {"__ndarray__": {"dtype": "|O", "shape": [1], "data": "AAAAAAAAAAA="}}
        for data in [
            {"__pickle__": "gASV"},
            {"a": 1, "b": 2},
            {"__float__": "1e400"},
            object_array,
            {"__ndarray__": {"dtype": "<f8", "shape": [2], "data": "AAAA"}},
        ]:
            with self.subTest(data=data), self.assertRaises(NotPlainData):
                decode(data)


if __name__ == "__main__":
    unittest.main()
