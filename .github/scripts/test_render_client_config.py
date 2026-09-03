import os
import subprocess
import sys
import unittest
from pathlib import Path

import yaml

SCRIPT = Path(__file__).with_name("render_client_config.py")


class RenderClientConfigTests(unittest.TestCase):
    def render(self, config: str, *, goproxy: str = "") -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["CLIENT_CONFIG"] = config
        env["GOPROXY"] = goproxy
        env.pop("GITHUB_OUTPUT", None)
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--file", "unused.yaml"],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_accepts_hive_defaults_without_build_args(self) -> None:
        result = self.render("- client: go-ethereum\n  dockerfile: git\n")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            yaml.safe_load(result.stdout),
            [{"client": "go-ethereum", "dockerfile": "git"}],
        )

    def test_goproxy_creates_build_args_when_absent(self) -> None:
        result = self.render(
            "- client: go-ethereum\n  dockerfile: git\n",
            goproxy="https://proxy.example",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            yaml.safe_load(result.stdout)[0]["build_args"],
            {"GOPROXY": "https://proxy.example"},
        )

    def test_rejects_non_string_build_args(self) -> None:
        result = self.render("- client: go-ethereum\n  build_args:\n    tag: 123\n")

        self.assertEqual(result.returncode, 1)
        self.assertIn("must map strings to strings", result.stderr)


if __name__ == "__main__":
    unittest.main()
