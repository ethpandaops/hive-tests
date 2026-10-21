import importlib.util
import json
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("update_listing.py")
spec = importlib.util.spec_from_file_location("update_listing", SCRIPT)
update_listing = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update_listing)
missing = update_listing.missing
merge = update_listing.merge


def line(file: str, sim_log: str = "") -> str:
    """Return a listing line as hiveview writes it."""
    return json.dumps({"name": "eels/consume-engine", "fileName": file, "simLog": sim_log or f"{file}.log"})


class MissingTests(unittest.TestCase):
    def test_lists_only_files_without_a_line(self) -> None:
        listing = [line("2.json"), line("1.json")]
        self.assertEqual(missing(listing, ["1.json", "2.json", "3.json"], 10), ["3.json"])

    def test_skips_files_hiveview_does_not_list(self) -> None:
        names = ["hive.json", "errorReport.json", "containerErrorReport.json", ".1.json", "1.log", "1.json"]
        self.assertEqual(missing([], names, 10), ["1.json"])

    def test_ignores_files_older_than_the_limit(self) -> None:
        listing = [line("3.json"), line("2.json")]
        self.assertEqual(missing(listing, ["1.json", "2.json", "3.json", "4.json"], 3), ["4.json"])

    def test_empty_listing_lists_everything(self) -> None:
        self.assertEqual(missing([], ["1.json", "2.json"], 10), ["2.json", "1.json"])


class MergeTests(unittest.TestCase):
    def test_adds_new_lines_and_sorts_by_simulator_log(self) -> None:
        listing = [line("2.json", "20-sim.log"), line("1.json", "10-sim.log")]
        new = [line("3.json", "30-sim.log")]
        self.assertEqual(
            merge(listing, new, ["1.json", "2.json", "3.json"], 10),
            [new[0], listing[0], listing[1]],
        )

    def test_drops_lines_of_expired_files(self) -> None:
        listing = [line("2.json"), line("1.json")]
        self.assertEqual(merge(listing, [], ["2.json"], 10), [listing[0]])

    def test_keeps_the_newest_files_up_to_the_limit(self) -> None:
        listing = [line("2.json", "2.log"), line("1.json", "1.log")]
        new = [line("3.json", "3.log")]
        self.assertEqual(merge(listing, new, ["1.json", "2.json", "3.json"], 2), [new[0], listing[0]])

    def test_keeps_old_lines_byte_for_byte(self) -> None:
        # hiveview escapes & as &, which json.dumps would not.
        old = '{"fileName":"1.json","simLog":"1.log","versions":{"besu":"a \\u0026 b"}}'
        self.assertEqual(merge([old], [], ["1.json"], 10), [old])

    def test_new_line_replaces_an_old_line_of_the_same_file(self) -> None:
        old, new = line("1.json", "old.log"), line("1.json", "new.log")
        self.assertEqual(merge([old], [new], ["1.json"], 10), [new])


if __name__ == "__main__":
    unittest.main()
