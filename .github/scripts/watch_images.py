# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "PyYAML==6.0.3",
# ]
# ///

"""
Dispatch the hive dashboard workflows whose images changed.

Watches every `hive-*.yaml` workflow without a schedule. For each, it
resolves the fixtures release and renders the default client file as
the workflow's prepare job does, then reads the current digest of each
default client's image and each default EELS simulator's image. Against
the digests of the previous check (`--previous`):

- a new fixtures release in an EELS simulator image dispatches that
  simulator for every client with a published image. Rebuilds of the
  same release, which follow every framework change, dispatch nothing,
  and the next run of each client picks them up
- a changed client image dispatches that client for the simulators
  whose image did not change, so no run is dispatched twice

A new devnet moves every image tag, so it dispatches every client and
simulator. An image that is not published yet dispatches nothing, and
its client runs once the image appears. A workflow missing from the
previous check, as on the very first, is only recorded. Writes the
digests to `--state`, and dispatches only with `--dispatch`.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))

import images  # noqa: E402
import render_client_config  # noqa: E402
import resolve_fixtures_release  # noqa: E402

WORKFLOWS = ROOT / ".github" / "workflows"
CONFIG_DIR = ROOT / render_client_config.CONFIG_DIR
EELS = "ethereum/eels/"
# Default image of an EELS simulator, see its Dockerfile in hive.
EELS_IMAGE = "ghcr.io/ethereum/execution-specs/hive/{name}"
# Labels the EELS images record their fixtures or tests release in.
EELS_RELEASE_LABELS = ("org.ethereum.eest.fixtures-release", "org.ethereum.eest.tests-release")


def split_list(value: str) -> list:
    """Split a workflow input such as `"besu","reth"` into names."""
    return re.findall(r'"([^"]+)"', value)


def join_list(names: list) -> str:
    """Join names into a workflow input such as `"besu","reth"`."""
    return ",".join(f'"{name}"' for name in names)


def settings(workflow: dict) -> dict:
    """Return what a dashboard workflow runs by default."""
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    steps = workflow["jobs"]["prepare"]["steps"]
    (resolver,) = [step["run"] for step in steps if step.get("name") == "Resolve fixtures release"]
    devnet = re.search(r"--devnet-name '([^']+)'", resolver)
    return {
        "clients": split_list(inputs["client"]["default"]),
        "simulators": split_list(inputs["simulator"]["default"]),
        "client_file": inputs["client_file"]["default"],
        "prefix": re.search(r"--prefix (\S+)", resolver).group(1),
        "devnet": devnet.group(1) if devnet else None,
    }


def watched() -> dict:
    """Return the settings of each dashboard workflow without a schedule."""
    result = {}
    for path in sorted(WORKFLOWS.glob("hive-*.yaml")):
        workflow = yaml.safe_load(path.read_text())
        if "schedule" not in workflow[True]:
            result[path.name] = settings(workflow)
    return result


def image_refs(entries: list, clients: list, simulators: list) -> dict:
    """Return the image each default client and EELS simulator runs from."""
    result = {}
    for entry in entries:
        args = entry.get("build_args", {})
        if entry.get("client") in clients and "baseimage" in args:
            result[f"client:{entry['client']}"] = f"{args['baseimage']}:{args.get('tag', 'latest')}"
        simulator = entry.get("simulator", "")
        if simulator in simulators and simulator.startswith(EELS) and "dockerfile" not in entry and "tag" in args:
            image = args.get("image", EELS_IMAGE.format(name=simulator.removeprefix(EELS)))
            result[f"simulator:{simulator}"] = f"{image}:{args['tag']}"
    return result


def eels_release(config: dict) -> str | None:
    """Return the fixtures or tests release an EELS image config records."""
    labels = config.get("config", {}).get("Labels") or {}
    return next((labels[label] for label in EELS_RELEASE_LABELS if labels.get(label)), None)


def simulator_version(image: str) -> str | None:
    """Return the release an EELS simulator image carries, else its digest.

    None if the image is not published.
    """
    reference, tag = image.rsplit(":", 1)
    source = images.registry(reference)
    if source is None or source[0] != "ghcr":
        return images.digest(image)
    repository = source[1]
    token = images.ghcr_token(repository)
    response = images.ghcr(repository, f"manifests/{tag}", token)
    if response is None:
        return None
    manifest = json.load(response)
    if "manifests" in manifest:
        platforms = [m for m in manifest["manifests"] if m.get("platform", {}).get("architecture") == "amd64"]
        manifest = json.load(images.ghcr(repository, f"manifests/{(platforms or manifest['manifests'])[0]['digest']}", token))
    config = json.load(images.ghcr(repository, f"blobs/{manifest['config']['digest']}", token))
    return eels_release(config) or images.digest(image)


def current(workflows: dict) -> dict:
    """Return, per watched workflow, each image it runs from and its digest."""
    releases, digests, state = {}, {}, {}
    for name, config in workflows.items():
        prefix = config["prefix"]
        if prefix not in releases:
            releases[prefix] = resolve_fixtures_release.resolve(prefix)
        tag = releases[prefix]
        major, minor, patch = resolve_fixtures_release.version_key(tag)
        variables = {"EELS_IMAGE_TAG": resolve_fixtures_release.image_tag(prefix, tag, pinned=False)}
        if config["devnet"]:
            variables["DEVNET"] = config["devnet"].format(major=major, minor=minor, patch=patch)
        path = CONFIG_DIR / config["client_file"]
        entries = render_client_config.load(str(path), path.read_text(), variables)
        state[name] = {}
        for key, image in image_refs(entries, config["clients"], config["simulators"]).items():
            if image not in digests:
                digests[image] = simulator_version(image) if key.startswith("simulator:") else images.digest(image)
            state[name][key] = f"{image}@{digests[image] or ''}"
    return state


def plan(state: dict, previous: dict, workflows: dict) -> list:
    """Return the dispatches, as (workflow, inputs), for the changed images."""
    dispatches = []
    for name, images_now in state.items():
        if name not in previous:
            continue
        changed = {
            key
            for key, value in images_now.items()
            if value != previous[name].get(key) and not value.endswith("@")
        }
        simulators = [s for s in workflows[name]["simulators"] if f"simulator:{s}" in changed]
        clients = [c for c in workflows[name]["clients"] if f"client:{c}" in changed]
        unchanged = [s for s in workflows[name]["simulators"] if s not in simulators]
        # Clients without a published image would only fail to start.
        runnable = [
            c for c in workflows[name]["clients"] if not images_now.get(f"client:{c}", "").endswith("@")
        ]
        if simulators and runnable:
            dispatches.append((name, {"client": join_list(runnable), "simulator": join_list(simulators)}))
        if clients and unchanged:
            dispatches.append((name, {"client": join_list(clients), "simulator": join_list(unchanged)}))
    return dispatches


def dispatch(workflow: str, inputs: dict) -> None:
    """Dispatch a workflow on the ref this check runs on."""
    repository = os.environ["GITHUB_REPOSITORY"]
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/actions/workflows/{workflow}/dispatches",
        method="POST",
        data=json.dumps({"ref": os.environ["GITHUB_REF_NAME"], "inputs": inputs}).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "Accept": "application/vnd.github+json",
        },
    )
    urllib.request.urlopen(request, timeout=30)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--previous", required=True, help="digests of the previous check")
    parser.add_argument("--state", required=True, help="file to write the current digests to")
    parser.add_argument("--dispatch", action="store_true", help="dispatch the runs")
    args = parser.parse_args()

    previous = json.loads(Path(args.previous).read_text() or "{}")
    workflows = watched()
    state = current(workflows)
    dispatches = plan(state, previous, workflows)
    for name in state:
        if name not in previous:
            print(f"{name}: recorded")
    for workflow, inputs in dispatches:
        print(f"{workflow}: {inputs}")
        if args.dispatch:
            dispatch(workflow, inputs)
    if not dispatches:
        print("no image changed")
    Path(args.state).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
