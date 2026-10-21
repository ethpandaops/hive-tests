"""
Update a hive results listing without downloading every result file.

`hiveview --listing` builds `listing.jsonl` from the newest `--limit`
suite files of a results directory, one line per run, so rebuilding it
from scratch means fetching every suite file kept in S3. The lines of
the current listing are still valid, so only the suite files it lacks
need fetching:

- `missing` prints the newest `--limit` suite files of `--names` (the
  results directory in S3) that `--listing` has no line for.
- `merge` combines the lines of `--listing` and `--new` (hiveview's
  listing of the missing files) for those newest suite files, sorted as
  hiveview sorts them, and prints the updated listing. Lines of expired
  files are dropped, and old lines are kept byte for byte.
"""

import argparse
import json
import sys

# Files of a results directory that hiveview does not list.
SKIPPED = {"errorReport.json", "containerErrorReport.json", "hive.json"}


def read_lines(path: str) -> list:
    """Return the non-empty lines of a file."""
    with open(path) as handle:
        return [line.rstrip("\n") for line in handle if line.strip()]


def newest(names: list, limit: int) -> list:
    """Return the suite files hiveview lists: the newest `limit` by name."""
    suites = {
        name
        for name in names
        if name.endswith(".json") and name not in SKIPPED and not name.startswith(".")
    }
    return sorted(suites, reverse=True)[:limit]


def by_file(lines: list) -> dict:
    """Map each listing line to the suite file it describes."""
    return {json.loads(line)["fileName"]: line for line in lines}


def missing(listing: list, names: list, limit: int) -> list:
    """Return the newest suite files that have no listing line."""
    listed = by_file(listing)
    return [name for name in newest(names, limit) if name not in listed]


def merge(listing: list, new: list, names: list, limit: int) -> list:
    """Return the listing lines for the newest suite files, newest run first."""
    lines = by_file(listing) | by_file(new)
    kept = [lines[name] for name in newest(names, limit) if name in lines]
    return sorted(kept, key=lambda line: json.loads(line)["simLog"], reverse=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=["missing", "merge"])
    parser.add_argument("--listing", required=True, help="current listing.jsonl")
    parser.add_argument("--names", required=True, help="file names in the results directory")
    parser.add_argument("--new", help="hiveview listing of the missing files, for merge")
    parser.add_argument("--limit", type=int, required=True, help="number of runs to list")
    args = parser.parse_args()

    listing = read_lines(args.listing)
    names = read_lines(args.names)
    if args.command == "missing":
        result = missing(listing, names, args.limit)
    else:
        if not args.new:
            sys.exit("merge needs --new")
        result = merge(listing, read_lines(args.new), names, args.limit)
    for line in result:
        print(line)


if __name__ == "__main__":
    main()
