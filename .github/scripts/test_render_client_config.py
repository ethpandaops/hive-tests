import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("render_client_config.py")
spec = importlib.util.spec_from_file_location("render_client_config", SCRIPT)
render_client_config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_client_config)
validate = render_client_config.validate

CLIENT = {"client": "go-ethereum", "build_args": {"tag": "master"}}


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
