# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "PyYAML==6.0.3",
# ]
# ///

"""
Select the clients a hive dashboard run can start.

Reads the requested clients (`CLIENTS`, e.g. `"besu","reth"`) and the
rendered client file (`CLIENT_CONFIG`). Keeps each client whose image is
published, or whose branch or tag exists for a `dockerfile: git` build,
so a client with no image or branch for a devnet yet is skipped up front
instead of failing its jobs. A client without an entry, with a commit as
its git tag, or with an image in a registry that can't be checked is
kept. Writes the kept clients to the `clients` step output as a JSON
list, and lists the skipped ones in the step summary.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

import images  # noqa: E402


def split_list(value: str) -> list:
    """Split a workflow input such as `"besu","reth"` into names."""
    return re.findall(r'"([^"]+)"', value)


def source(entry: dict) -> tuple | None:
    """Return what a client entry builds from, or None if it can't be checked."""
    args = entry.get("build_args", {})
    if entry.get("dockerfile") == "git":
        if "github" in args and "tag" in args and not re.fullmatch(r"[0-9a-f]{7,40}", args["tag"]):
            return "branch", args["github"], args["tag"]
        return None
    if "baseimage" in args and images.registry(args["baseimage"]) is not None:
        return "image", f"{args['baseimage']}:{args.get('tag', 'latest')}"
    return None


def image_exists(image: str) -> bool:
    return images.digest(image) is not None


def branch_exists(repository: str, ref: str) -> bool:
    """Return whether a GitHub repository has a branch or tag named ref."""
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", f"https://github.com/{repository}", f"refs/heads/{ref}", f"refs/tags/{ref}"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode not in (0, 2):
        sys.exit(f"git ls-remote {repository} failed: {result.stderr.strip()}")
    return result.returncode == 0


def select(clients: list, entries: list, image_exists, branch_exists) -> tuple:
    """Return the clients that can start and those to skip, with the reason."""
    kept, skipped = [], []
    for name in clients:
        entry = next((e for e in entries if e.get("client") == name), None)
        built_from = source(entry) if entry else None
        if built_from is None:
            kept.append(name)
        elif built_from[0] == "image" and not image_exists(built_from[1]):
            skipped.append((name, f"image {built_from[1]} is not published"))
        elif built_from[0] == "branch" and not branch_exists(built_from[1], built_from[2]):
            skipped.append((name, f"{built_from[1]} has no branch or tag {built_from[2]}"))
        else:
            kept.append(name)
    return kept, skipped


def main() -> None:
    clients = split_list(os.environ["CLIENTS"])
    entries = yaml.safe_load(os.environ["CLIENT_CONFIG"]) or []
    kept, skipped = select(clients, entries, image_exists, branch_exists)
    lines = [f"Running: {', '.join(kept) or 'none'}"]
    lines += [f"Skipped {name}: {reason}" for name, reason in skipped]
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as handle:
            handle.write("\n".join(f"- {line}" for line in lines) + "\n")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as handle:
            handle.write(f"clients={json.dumps(kept)}\n")


if __name__ == "__main__":
    main()
