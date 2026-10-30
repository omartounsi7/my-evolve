"""The messages between the host and the sandbox worker: one JSON object per line.

The host sends:
    {"type": "load", "code": "..."}                                  run the program
    {"type": "call", "id": 1, "name": "f", "args": [...], "kwargs": {...}}
    {"type": "get", "id": 2, "name": "N"}                            a plain-data global

The worker answers:
    {"type": "loaded", "names": {"f": "function", "N": "data", "np": "other"}}
    {"type": "load_failed", "error": "...", "traceback": "..."}
    {"type": "return", "id": 1, "value": ...}
    {"type": "raised", "id": 1, "error": "...", "traceback": "..."}

Arguments and values are plain data, written with encode and read back with decode, so
that they come back exactly as they were sent:

    None, booleans, integers, text, finite floats    as they are
    lists                                             item by item
    tuples                                            {"__tuple__": [...]}
    dictionaries with text keys                       {"__dict__": {...}}
    nan, inf and -inf                                 {"__float__": "nan"}
    numpy arrays of numbers                           {"__ndarray__": {"dtype": "<f8",
                                                         "shape": [26, 2], "data": base64}}
    numpy numbers                                     the Python number of the same value

Anything else is refused (NotPlainData). Arrays are rebuilt from their bytes for number
types only, never through pickle, so the program cannot send the host code to run.

This module, like the worker, imports nothing outside Python's standard library. numpy
is imported only when a numpy value is met, so it is optional on both sides.
"""

import base64
import json
import math
from typing import IO, Any

# One message: a JSON object, read as a dictionary
Message = dict[str, Any]

# The kinds of numpy arrays that may travel: booleans, integers, unsigned, floats, complex
NUMBER_KINDS = "biufc"
# The text of the floats JSON cannot write
NON_FINITE_FLOATS = ("nan", "inf", "-inf")


class NotPlainData(TypeError):
    """Raised for a value that cannot travel between the host and the worker."""


def encode(value: Any) -> Any:
    """Return value as JSON data that decode turns back into the same value.

    Raises NotPlainData for a value that is not plain data.
    """
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        number = float(value)
        return number if math.isfinite(number) else {"__float__": repr(number)}
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, tuple):
        return {"__tuple__": [encode(item) for item in value]}
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise NotPlainData("a dictionary's keys must be text")
        return {"__dict__": {key: encode(item) for key, item in value.items()}}
    # numpy values, recognized without importing numpy unless one is met
    if type(value).__module__ == "numpy":
        import numpy

        if isinstance(value, numpy.ndarray):
            return encode_array(value)
        if isinstance(value, numpy.generic):
            return encode(value.item())
    raise NotPlainData(f"a value of type {type(value).__name__} is not plain data")


def encode_array(array: Any) -> Any:
    """Return a numpy array of numbers as its type, shape and bytes."""
    import numpy

    if array.dtype.kind not in NUMBER_KINDS:
        raise NotPlainData(f"an array of {array.dtype} is not an array of numbers")
    data = numpy.ascontiguousarray(array).tobytes()
    return {
        "__ndarray__": {
            "dtype": array.dtype.str,
            "shape": list(array.shape),
            "data": base64.b64encode(data).decode("ascii"),
        }
    }


def decode(value: Any) -> Any:
    """Return the value encode wrote as value. Raises NotPlainData for anything else."""
    if isinstance(value, list):
        return [decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if len(value) != 1:
        raise NotPlainData("an encoded object must have exactly one tag")
    ((tag, content),) = value.items()
    if tag == "__tuple__" and isinstance(content, list):
        return tuple(decode(item) for item in content)
    if tag == "__dict__" and isinstance(content, dict):
        return {key: decode(item) for key, item in content.items()}
    if tag == "__float__" and content in NON_FINITE_FLOATS:
        return float(content)
    if tag == "__ndarray__" and isinstance(content, dict):
        return decode_array(content)
    raise NotPlainData(f"cannot decode the tag {tag!r}")


def decode_array(content: dict[str, Any]) -> Any:
    """Rebuild a numpy array of numbers from its type, shape and bytes."""
    try:
        import numpy
    except ImportError:
        raise NotPlainData("numpy is needed to receive an array") from None
    try:
        dtype = numpy.dtype(content["dtype"])
        if dtype.kind not in NUMBER_KINDS:
            raise NotPlainData(f"an array of {dtype} is not an array of numbers")
        data = base64.b64decode(content["data"], validate=True)
        # copy: an array built on bytes would be read-only.
        return numpy.frombuffer(data, dtype=dtype).reshape(content["shape"]).copy()
    except (KeyError, TypeError, ValueError) as error:
        raise NotPlainData(f"a malformed array: {error}") from None


def send(stream: IO[str], message: Message) -> None:
    """Write one message as one line, and make sure it leaves at once."""
    stream.write(json.dumps(message, allow_nan=False) + "\n")
    stream.flush()


def receive(stream: IO[str]) -> Message | None:
    """Read one message; None when the stream has ended. Raises ValueError for a bad line."""
    line = stream.readline()
    if not line:
        return None
    message = json.loads(line)
    if not isinstance(message, dict):
        raise ValueError(f"a message must be a JSON object, got {line!r}")
    return message
