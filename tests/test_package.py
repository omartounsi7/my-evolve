"""Checks that what the container imports needs none of the host's dependencies.

The evaluation container imports my_evolve.sandbox_worker, but has none of the
packages the host needs (openai, yaml, ...). The package itself and the worker
must therefore load nothing beyond Python's standard library.
"""

import subprocess
import sys
import unittest

# Third-party packages the host uses, which the container does not have.
HOST_ONLY_PACKAGES = ("openai", "yaml", "numpy", "matplotlib")

# Run in a fresh interpreter, so that what this test process imported does not count.
# It prints the top-level names of every module loaded once the module is imported.
IMPORT_SCRIPT = (
    "import importlib, sys; importlib.import_module(sys.argv[1]); "
    "print(' '.join(sorted({name.split('.')[0] for name in sys.modules})))"
)


def modules_loaded_by(module: str) -> set[str]:
    """Return the top-level names of the modules a fresh interpreter loads to import module."""
    result = subprocess.run(
        # -I: ignore the current folder and environment variables, as the container would.
        [sys.executable, "-I", "-c", IMPORT_SCRIPT, module],
        capture_output=True,
        text=True,
        check=True,
    )
    return set(result.stdout.split())


class TestPackage(unittest.TestCase):
    """The modules the container uses must stay free of third-party imports."""

    def test_package_and_worker_load_no_host_only_package(self) -> None:
        for module in ("my_evolve", "my_evolve.sandbox_worker", "my_evolve.sandbox_protocol"):
            with self.subTest(module=module):
                loaded = modules_loaded_by(module)
                self.assertIn("my_evolve", loaded)
                for package in HOST_ONLY_PACKAGES:
                    self.assertNotIn(package, loaded)


if __name__ == "__main__":
    unittest.main()
