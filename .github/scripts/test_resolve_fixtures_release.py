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


if __name__ == "__main__":
    unittest.main()
