"""
Resolve the fixtures release a hive workflow should consume.

Picks the greatest published `<prefix>@vX.Y.Z` release of
ethereum/execution-specs, or validates a pinned tag from the
`FIXTURES_TAG` environment variable. Draft releases are invisible to
the API, so workflows stay on the previous release until a new one is
published. Writes `EELS_BUILD_ARG_FIXTURES=<download url>` to
`GITHUB_ENV` and logs the chosen tag to `GITHUB_STEP_SUMMARY` when
those files are available, and always prints the tag.

Devnet workflows derive the rest of their wiring from the tag: with
`--devnet-branch devnets/frames/{major}` the EELS branch follows the
release's major version (`tests-frames-devnet@v1.2.3` builds EELS from
`devnets/frames/1`) and is written as `EELS_BUILD_ARG_BRANCH`, and with
`--devnet-name frames-devnet-{major}` the devnet name the clients branch
on is written as `DEVNET`. Templates may use `{major}`, `{minor}` and
`{patch}`. Every value is also written to `GITHUB_OUTPUT` as
`fixtures_tag`, `fixtures_url`, `eels_branch` and `devnet` so a
preparation job can hand them to the test matrix.
"""

import argparse
import json
import os
import sys
import urllib.request

RELEASES_URL = (
    "https://api.github.com/repos/ethereum/execution-specs/"
    "releases?per_page=100"
)


def version_key(tag: str) -> tuple:
    """Sort key for a `<prefix>@vX.Y.Z` tag."""
    version = tag.split("@v", 1)[1]
    return tuple(int(part) for part in version.split("."))


def resolve(prefix: str) -> str:
    """Return the greatest published release tag for the prefix."""
    request = urllib.request.Request(RELEASES_URL)
    token = os.environ.get("GH_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        releases = json.load(response)
    tags = [
        release["tag_name"]
        for release in releases
        if release["tag_name"].startswith(f"{prefix}@v")
        and not release["draft"]
    ]
    if not tags:
        sys.exit(f"no published {prefix} release found")
    return max(tags, key=version_key)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", required=True, help="release tag family")
    parser.add_argument("--asset", required=True, help="fixtures asset name")
    parser.add_argument(
        "--devnet-branch",
        help="EELS branch template, e.g. devnets/frames/{major}",
    )
    parser.add_argument(
        "--devnet-name",
        help="devnet name template, e.g. frames-devnet-{major}",
    )
    args = parser.parse_args()

    tag = os.environ.get("FIXTURES_TAG", "").strip()
    if tag:
        if not tag.startswith(f"{args.prefix}@v"):
            sys.exit(f"pinned tag {tag} is not a {args.prefix} release")
    else:
        tag = resolve(args.prefix)

    url = (
        "https://github.com/ethereum/execution-specs/releases/download/"
        f"{tag}/{args.asset}"
    )
    major, minor, patch = version_key(tag)
    version = {"major": major, "minor": minor, "patch": patch}
    env = {"EELS_BUILD_ARG_FIXTURES": url}
    outputs = {"fixtures_tag": tag, "fixtures_url": url}
    if args.devnet_branch:
        branch = args.devnet_branch.format(**version)
        env["EELS_BUILD_ARG_BRANCH"] = branch
        outputs["eels_branch"] = branch
    if args.devnet_name:
        devnet = args.devnet_name.format(**version)
        env["DEVNET"] = devnet
        outputs["devnet"] = devnet

    print(tag)
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as env_file:
            for key, value in env.items():
                env_file.write(f"{key}={value}\n")
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as output_file:
            for key, value in outputs.items():
                output_file.write(f"{key}={value}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as summary_file:
            summary_file.write(f"Using fixtures release: `{tag}`\n")
            if args.devnet_branch:
                summary_file.write(f"Building EELS from: `{branch}`\n")
            if args.devnet_name:
                summary_file.write(f"Client branches: `{devnet}`\n")


if __name__ == "__main__":
    main()
