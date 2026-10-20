import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("resolve_fixtures_release.py")
spec = importlib.util.spec_from_file_location("resolve_fixtures_release", SCRIPT)
resolve_fixtures_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resolve_fixtures_release)
image_tag = resolve_fixtures_release.image_tag


class ImageTagTests(unittest.TestCase):
    def test_mainnet_follows_latest(self) -> None:
        self.assertEqual(image_tag("tests", "tests@v21.0.1", pinned=False), "latest")

    def test_mainnet_pin_selects_the_release(self) -> None:
        self.assertEqual(image_tag("tests", "tests@v21.0.1", pinned=True), "v21.0.1")

    def test_devnet_follows_its_channel(self) -> None:
        self.assertEqual(
            image_tag("tests-bogota-devnet", "tests-bogota-devnet@v1.2.3", pinned=False),
            "bogota-devnet-1",
        )

    def test_devnet_pin_selects_the_release(self) -> None:
        self.assertEqual(
            image_tag("tests-heze-devnet", "tests-heze-devnet@v2.0.0", pinned=True),
            "heze-devnet-v2.0.0",
        )

    def test_other_series_have_no_images(self) -> None:
        with self.assertRaises(SystemExit):
            image_tag("tests-zkevm", "tests-zkevm@v21.0.5", pinned=False)


class OutputTests(unittest.TestCase):
    """The workflows still building from source keep their outputs."""

    def run_main(self, tmp: Path, tag: str, *args: str) -> dict:
        import os
        import sys
        from unittest import mock

        env_file = tmp / "env"
        output_file = tmp / "output"
        environ = {
            "FIXTURES_TAG": tag,
            "GITHUB_ENV": str(env_file),
            "GITHUB_OUTPUT": str(output_file),
        }
        argv = ["resolve_fixtures_release.py", *args]
        with mock.patch.dict(os.environ, environ), mock.patch.object(sys, "argv", argv):
            resolve_fixtures_release.main()
        lines = env_file.read_text().splitlines() + output_file.read_text().splitlines()
        return dict(line.split("=", 1) for line in lines)

    def test_image_only(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            values = self.run_main(Path(tmp), "tests@v21.0.1", "--prefix", "tests")
        self.assertEqual(values["EELS_IMAGE_TAG"], "v21.0.1")
        self.assertNotIn("EELS_BUILD_ARG_FIXTURES", values)

    def test_source_build_options_unchanged(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            values = self.run_main(
                Path(tmp),
                "tests-bogota-devnet@v1.1.0",
                "--prefix", "tests-bogota-devnet",
                "--asset", "fixtures_bogota-devnet.tar.gz",
                "--devnet-branch", "devnets/bogota/{major}",
                "--devnet-name", "bogota-devnet-{major}",
            )
        self.assertEqual(
            values["EELS_BUILD_ARG_FIXTURES"],
            "https://github.com/ethereum/execution-specs/releases/download/"
            "tests-bogota-devnet@v1.1.0/fixtures_bogota-devnet.tar.gz",
        )
        self.assertEqual(values["EELS_BUILD_ARG_BRANCH"], "devnets/bogota/1")
        self.assertEqual(values["DEVNET"], "bogota-devnet-1")
        self.assertEqual(values["eels_branch"], "devnets/bogota/1")
        self.assertEqual(values["EELS_IMAGE_TAG"], "bogota-devnet-v1.1.0")


if __name__ == "__main__":
    unittest.main()
