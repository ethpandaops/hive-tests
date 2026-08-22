"""
Resolve the fixtures release a hive workflow should consume.

Picks the greatest published `<prefix>@vX.Y.Z` release of
ethereum/execution-specs, or validates a pinned tag from the
`FIXTURES_TAG` environment variable. Draft releases are invisible to
the API, so workflows stay on the previous release until a new one is
published. Writes `EELS_BUILD_ARG_FIXTURES=<download url>` to
`GITHUB_ENV` and logs the chosen tag to `GITHUB_STEP_SUMMARY` when
those files are available, and always prints the tag.
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
    print(tag)
    github_env = os.environ.get("GITHUB_ENV")
    if github_env:
        with open(github_env, "a") as env_file:
            env_file.write(f"EELS_BUILD_ARG_FIXTURES={url}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as summary_file:
            summary_file.write(f"Using fixtures release: `{tag}`\n")


if __name__ == "__main__":
    main()
