"""
Resolve the fixtures release a hive workflow should consume.

Picks the greatest published `<prefix>@vX.Y.Z` release of
ethereum/execution-specs, or validates a pinned tag from the
`FIXTURES_TAG` environment variable. Draft releases are invisible to
the API, so workflows stay on the previous release until a new one is
published. Logs the chosen tag to `GITHUB_STEP_SUMMARY` when that file
is available, and always prints the tag.

The EELS simulators run the images execution-specs publishes for its
releases, selected with `--sim.buildarg tag=`, which is written to
`GITHUB_ENV` as `EELS_IMAGE_TAG`. Following the greatest release selects
its line's channel, which also picks up framework fixes: `latest` for
`tests`, and `bogota-devnet-1` for `tests-bogota-devnet@v1.2.3`. A
pinned tag selects that release's image, `v21.0.1` or
`bogota-devnet-v1.2.3`, which never changes.

Devnet workflows derive the client branches from the tag: with
`--devnet-name bogota-devnet-{major}` the devnet name the clients branch
on is written as `DEVNET`. Templates may use `{major}`, `{minor}` and
`{patch}`. Every value is also written to `GITHUB_OUTPUT` as
`fixtures_tag`, `image_tag` and `devnet` so a preparation job can hand
them to the test matrix.
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


def image_tag(prefix: str, tag: str, pinned: bool) -> str:
    """EELS simulator image tag for a release: its channel, or itself if pinned."""
    version = tag.split("@", 1)[1]
    if prefix == "tests":
        return version if pinned else "latest"
    name = prefix.removeprefix("tests-")
    if not name.endswith("-devnet"):
        sys.exit(f"{prefix} releases have no EELS simulator images")
    if pinned:
        return f"{name}-{version}"
    return f"{name}-{version_key(tag)[0]}"


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
    parser.add_argument(
        "--devnet-name",
        help="devnet name template, e.g. bogota-devnet-{major}",
    )
    args = parser.parse_args()

    tag = os.environ.get("FIXTURES_TAG", "").strip()
    pinned = bool(tag)
    if pinned:
        if not tag.startswith(f"{args.prefix}@v"):
            sys.exit(f"pinned tag {tag} is not a {args.prefix} release")
    else:
        tag = resolve(args.prefix)

    major, minor, patch = version_key(tag)
    version = {"major": major, "minor": minor, "patch": patch}
    image = image_tag(args.prefix, tag, pinned)
    env = {"EELS_IMAGE_TAG": image}
    outputs = {"fixtures_tag": tag, "image_tag": image}
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
            summary_file.write(f"EELS simulator image tag: `{image}`\n")
            if args.devnet_name:
                summary_file.write(f"Client branches: `{devnet}`\n")


if __name__ == "__main__":
    main()
