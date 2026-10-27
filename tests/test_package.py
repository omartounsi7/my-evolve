"""Checks that the my_evolve package can be imported without the host's dependencies.

The evaluation container imports my_evolve.sandbox_worker, but has none of the
packages the host needs (openai, yaml, ...). Importing the package itself must
therefore load nothing beyond Python's standard library.
"""

import subprocess
import sys
import unittest

# Third-party packages the host uses, which the container does not have.
HOST_ONLY_PACKAGES = ("openai", "yaml", "numpy", "matplotlib")

# Run in a fresh interpreter, so that what this test process imported does not count.
# It prints the top-level names of every module loaded once my_evolve is imported.
IMPORT_SCRIPT = (
    "import sys, my_evolve; print(' '.join(sorted({name.split('.')[0] for name in sys.modules})))"
)


class TestPackage(unittest.TestCase):
    """The package's __init__ must stay free of third-party imports."""

    def test_importing_the_package_loads_no_host_only_package(self) -> None:
        result = subprocess.run(
            # -I: ignore the current folder and environment variables, as the container would.
            [sys.executable, "-I", "-c", IMPORT_SCRIPT],
            capture_output=True,
            text=True,
            check=True,
        )
        loaded = set(result.stdout.split())
        self.assertIn("my_evolve", loaded)
        for package in HOST_ONLY_PACKAGES:
            self.assertNotIn(package, loaded)


if __name__ == "__main__":
    unittest.main()
