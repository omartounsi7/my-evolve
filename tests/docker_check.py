"""Tells the tests whether Docker can be used on this machine."""

import functools
import shutil
import subprocess


@functools.cache
def docker_is_available() -> bool:
    """Return True if Docker is installed and running. Checked once per test run."""
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(["docker", "info"], capture_output=True, check=False)
    return result.returncode == 0
