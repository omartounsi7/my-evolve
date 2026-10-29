import numpy as np


CALLS = [0]


def run_search():
    CALLS[0] += 1
    if CALLS[0] % 2 == 0:
        return [][1]
    return -1.704, 0.678
