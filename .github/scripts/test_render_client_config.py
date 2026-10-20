import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().with_name("render_client_config.py")
spec = importlib.util.spec_from_file_location("render_client_config", SCRIPT)
render_client_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_client_config)
validate = render_client_config.validate

CLIENT = {"client": "go-ethereum", "build_args": {"tag": "master"}}
CLIENT_FILE = "- client: besu\n"
SIMULATOR_FILE = """\
- client: besu
- simulator: ethereum/eels/consume-engine
  build_args:
    tag: ${EELS_IMAGE_TAG}
"""
SIMULATOR_ENTRY = {"simulator": "ethereum/eels/consume-engine", "build_args": {"tag": "v21.0.1"}}


class RenderClientConfigTests(unittest.TestCase):
    def render(self, config: str, *, goproxy: str = "", file: str = CLIENT_FILE) -> subprocess.CompletedProcess:
        with tempfile.TemporaryDirectory() as root:
            config_dir = Path(root, ".github/configs/hive")
            config_dir.mkdir(parents=True)
            (config_dir / "test.yaml").write_text(file)
            env = os.environ.copy()
            env["CLIENT_CONFIG"] = config
            env["GOPROXY"] = goproxy
            env.pop("GITHUB_OUTPUT", None)
            return subprocess.run(
                [sys.executable, str(SCRIPT), "--file", "test.yaml", "--var", "EELS_IMAGE_TAG=v21.0.1"],
                cwd=root,
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

    def test_file_placeholders_are_filled(self) -> None:
        result = self.render("", file=SIMULATOR_FILE)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(yaml.safe_load(result.stdout), [{"client": "besu"}, SIMULATOR_ENTRY])

    def test_inline_config_keeps_file_simulator_entries(self) -> None:
        result = self.render("- client: go-ethereum\n", file=SIMULATOR_FILE)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(yaml.safe_load(result.stdout), [{"client": "go-ethereum"}, SIMULATOR_ENTRY])

    def test_inline_simulator_entries_replace_file_ones(self) -> None:
        inline = "- client: go-ethereum\n- simulator: ethereum/eels/consume-rlp\n"
        result = self.render(inline, file=SIMULATOR_FILE)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            yaml.safe_load(result.stdout),
            [{"client": "go-ethereum"}, {"simulator": "ethereum/eels/consume-rlp"}],
        )


class ValidateTests(unittest.TestCase):
    def test_simulator_entries_are_accepted(self) -> None:
        validate(
            [
                CLIENT,
                {"simulator": "ethereum/eels/consume-engine", "build_args": {"tag": "latest"}},
                {"simulator": "ethereum/eels/consume-rlp", "dockerfile": "git"},
            ],
            "test",
        )

    def test_simulator_entry_rejects_client_keys(self) -> None:
        with self.assertRaises(SystemExit):
            validate([CLIENT, {"simulator": "ethereum/eels/consume-engine", "nametag": "x"}], "test")

    def test_simulator_build_args_must_be_strings(self) -> None:
        with self.assertRaises(SystemExit):
            validate([CLIENT, {"simulator": "ethereum/eels/consume-engine", "build_args": {"tag": 1}}], "test")

    def test_client_entries_unchanged(self) -> None:
        with self.assertRaises(SystemExit):
            validate([{"client": "go-ethereum", "simulator_typo": "x"}], "test")


if __name__ == "__main__":
    unittest.main()
