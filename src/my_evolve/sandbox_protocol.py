"""The messages between the host and the program's worker, and how values travel in them (D77).

Each message is one line of JSON. The values a program's functions receive and
return are "plain data": None, booleans, numbers, text, lists, tuples,
dictionaries with text keys, and numpy arrays of numbers. Anything else is
refused. Values never travel through pickle, which could run code when read (D8).

This module runs inside the evaluation container too, so it imports nothing but
Python's standard library; numpy is used only if the value to encode or decode
needs it.

Messages:

| From   | type        | Other keys                                         |
|--------|-------------|----------------------------------------------------|
| host   | load        | code                                               |
| host   | call        | id, name, args (a list), kwargs (a dictionary)     |
| host   | get         | id, name                                           |
| worker | loaded      | names: each top-level name and its kind            |
| worker | load_failed | error, traceback                                   |
| worker | return      | id, value                                          |
| worker | raised      | id, error, traceback                               |
"""

import base64
import json
import math
import sys
from typing import IO, Any

# The keys that mark a tagged value; each tagged value is a dictionary with one of them.
FLOAT_TAG = "__float__"
TUPLE_TAG = "__tuple__"
DICT_TAG = "__dict__"
ARRAY_TAG = "__ndarray__"

# The text forms of the floats JSON cannot hold.
NON_FINITE_FLOATS = {"nan": math.nan, "inf": math.inf, "-inf": -math.inf}

# The kinds of numpy arrays that may travel: booleans, integers, unsigned integers, floats.
ARRAY_KINDS = "biuf"

# The kinds of a program's top-level names, in the loaded message.
FUNCTION = "function"
DATA = "data"
OTHER = "other"


class NotPlainData(TypeError):
    """A value that cannot travel between the host and the worker."""


class ProtocolError(ValueError):
    """A line that is not a message of the protocol."""


def numpy_module() -> Any:
    """Return numpy if it has been imported in this process, otherwise None.

    A value can only be a numpy object if numpy is already imported, so this never
    imports it.
    """
    return sys.modules.get("numpy")


def encode(value: Any) -> Any:
    """Return value as plain JSON values, tagging what JSON would change.

    Raises NotPlainData for any value that is not plain data.
    """
    # bool first: True is also an int.
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if math.isfinite(value):
            return float(value)
        return {FLOAT_TAG: "nan" if math.isnan(value) else ("inf" if value > 0 else "-inf")}
    if isinstance(value, str):
        return str(value)
    if isinstance(value, list):
        return [encode(item) for item in value]
    if isinstance(value, tuple):
        return {TUPLE_TAG: [encode(item) for item in value]}
    if isinstance(value, dict):
        for key in value:
            if not isinstance(key, str):
                raise NotPlainData(f"dictionary keys must be text, got {type(key).__name__}")
        return {DICT_TAG: {key: encode(item) for key, item in value.items()}}

    numpy = numpy_module()
    if numpy is not None:
        if isinstance(value, numpy.ndarray):
            return encode_array(value)
        if isinstance(value, numpy.generic) and value.dtype.kind in ARRAY_KINDS:
            # A numpy number, such as numpy.float64(2.5): sent as the Python number.
            return encode(value.item())
    raise NotPlainData(f"a value of type {type(value).__name__} is not plain data")


def encode_array(array: Any) -> dict[str, Any]:
    """Return a numpy array of numbers as its type, its shape and its bytes in base64."""
    if array.dtype.kind not in ARRAY_KINDS:
        raise NotPlainData(f"only arrays of numbers are plain data, got dtype {array.dtype}")
    numpy = numpy_module()
    data = numpy.ascontiguousarray(array).tobytes()
    return {
        ARRAY_TAG: {
            # Such as "<f8": little-endian 8-byte floats.
            "dtype": array.dtype.str,
            "shape": list(array.shape),
            "data": base64.b64encode(data).decode("ascii"),
        }
    }


def decode(value: Any) -> Any:
    """Return the value that encode turned into value.

    Raises ProtocolError for a dictionary that is not a known tag.
    """
    if isinstance(value, list):
        return [decode(item) for item in value]
    if not isinstance(value, dict):
        return value
    if len(value) != 1:
        raise ProtocolError("a dictionary must be a tagged value")
    tag, content = next(iter(value.items()))
    if tag == FLOAT_TAG:
        if content not in NON_FINITE_FLOATS:
            raise ProtocolError(f"unknown float {content!r}")
        return NON_FINITE_FLOATS[content]
    if tag == TUPLE_TAG:
        return tuple(decode(item) for item in content)
    if tag == DICT_TAG:
        return {key: decode(item) for key, item in content.items()}
    if tag == ARRAY_TAG:
        return decode_array(content)
    raise ProtocolError(f"unknown tag {tag!r}")


def decode_array(content: dict[str, Any]) -> Any:
    """Rebuild a numpy array from its type, shape and bytes; only arrays of numbers."""
    try:
        import numpy
    except ImportError:
        raise NotPlainData("an array was sent, but numpy is not installed here") from None
    dtype = numpy.dtype(content["dtype"])
    if dtype.kind not in ARRAY_KINDS:
        raise ProtocolError(f"only arrays of numbers are plain data, got dtype {dtype}")
    data = base64.b64decode(content["data"])
    # copy(): frombuffer gives a read-only array over the bytes.
    return numpy.frombuffer(data, dtype=dtype).reshape(content["shape"]).copy()


def send(stream: IO[str], message: dict[str, Any]) -> None:
    """Write one message as one line of JSON, and flush it.

    The message's values must already be encoded. Only ASCII is written, so the
    line reads the same whatever the stream's encoding.
    """
    stream.write(json.dumps(message, allow_nan=False) + "\n")
    stream.flush()


def receive(stream: IO[str]) -> dict[str, Any] | None:
    """Read one message; None when the stream has ended.

    Raises ProtocolError if the line is not a JSON object with a "type".
    """
    line = stream.readline()
    if not line:
        return None
    try:
        message = json.loads(line)
    except json.JSONDecodeError as error:
        raise ProtocolError(f"not JSON: {error}") from None
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ProtocolError("a message must be a JSON object with a type")
    return message
