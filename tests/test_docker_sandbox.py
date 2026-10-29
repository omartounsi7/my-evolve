"""Checks the Docker sandbox: its image. Skipped when Docker is not installed or not running."""

import unittest

from docker_check import docker_is_available

from my_evolve.sandbox import ensure_image, image_tag, run_docker


class ImageTagTest(unittest.TestCase):
    def test_the_tag_changes_with_the_packages(self) -> None:
        """A different package list means a different image."""
        self.assertTrue(image_tag([]).startswith("my-evolve-evaluation:"))
        self.assertEqual(image_tag(["numpy==2.5.4"]), image_tag(["numpy==2.5.4"]))
        self.assertNotEqual(image_tag(["numpy==2.5.4"]), image_tag(["numpy==2.5.3"]))
        self.assertNotEqual(image_tag([]), image_tag(["numpy==2.5.4"]))


@unittest.skipUnless(docker_is_available(), "Docker is not available")
class ImageTest(unittest.TestCase):
    def test_the_image_is_built_once_then_reused(self) -> None:
        """ensure_image builds the image if needed; afterwards Docker has it."""
        tag = ensure_image([])
        self.assertEqual(tag, image_tag([]))
        self.assertEqual(run_docker(["image", "inspect", tag]).returncode, 0)
        self.assertEqual(ensure_image([]), tag)


if __name__ == "__main__":
    unittest.main()
