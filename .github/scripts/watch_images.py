# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "PyYAML==6.0.3",
# ]
# ///

"""
Dispatch the hive dashboard workflows whose images changed.

Watches every `hive-*.yaml` dashboard workflow without a schedule, and
every `sim-ethereum-eels-*.yaml` wrapper without one, which runs an EELS
simulator through `generic.yaml`. For each, it resolves the fixtures
release and renders the default client file as the prepare job does, then reads the current digest of each
default client's image and the release of each default EELS simulator's
image. The state (`--previous`, `--state`) records when each client and
simulator pair last ran, and with which images. A pair runs when:

- its images changed since it last ran. A new tag, as a new devnet
  brings, or a new fixtures release in an EELS image runs right away.
  A rebuild of the same client tag, as every push to a client's main
  branch brings, runs right away on a quick dashboard (`*-quick.yaml`)
  and for FAST_SIMULATORS, and at most every FULL_RUN_INTERVAL for the
  other simulators, whose runs take up to a day and a half per client
- its workflow's daily refresh hour passed, unless it ran in the
  RECENT_RUN before. The workflows' refresh hours are spread over the
  day, so their refreshes don't start in the same check, and a pair runs
  at least every day and a half. This also picks up changes the images
  don't show, in hive, the workflows or EELS rebuilds of the same
  release, and reruns failures

Clients due for the same simulators share one run, so no pair runs
twice. A pair with an image that is not published yet runs once the
image appears. A workflow missing from the previous state, as on the
very first check, is only recorded. Dispatches only with `--dispatch`.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
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
# How often a full dashboard reruns a pair for client rebuilds.
FULL_RUN_INTERVAL = timedelta(hours=12)
# A pair that ran less than this before its workflow's daily refresh hour,
# or since, skips the refresh.
RECENT_RUN = timedelta(hours=12)
# Simulators that take an hour or two per client, so every client rebuild
# reruns them.
FAST_SIMULATORS = ("ethereum/eels/consume-enginex", "ethereum/eels/execute-blobs")


def split_list(value: str) -> list:
    """Split a workflow input such as `"besu","reth"` into names."""
    return re.findall(r'"([^"]+)"', value)


def join_list(names: list) -> str:
    """Join names into a workflow input such as `"besu","reth"`."""
    return ",".join(f'"{name}"' for name in names)


def release_settings(workflow: dict) -> dict:
    """Return the fixtures release family and devnet a workflow resolves."""
    steps = workflow["jobs"]["prepare"]["steps"]
    (resolver,) = [step["run"] for step in steps if step.get("name") == "Resolve fixtures release"]
    devnet = re.search(r"--devnet-name '([^']+)'", resolver)
    return {
        "prefix": re.search(r"--prefix (\S+)", resolver).group(1),
        "devnet": devnet.group(1) if devnet else None,
    }


def settings(name: str, workflow: dict) -> dict:
    """Return what a dashboard workflow runs by default."""
    inputs = workflow[True]["workflow_dispatch"]["inputs"]
    return {
        "workflow": name,
        "clients": split_list(inputs["client"]["default"]),
        "simulators": split_list(inputs["simulator"]["default"]),
        "client_file": inputs["client_file"]["default"],
        "inputs": {},
        "quick": name.endswith("-quick.yaml"),
        **release_settings(workflow),
    }


def wrapper_settings(wrapper: dict, generic: dict) -> dict | None:
    """Return what an EELS wrapper runs through generic.yaml, or None.

    The wrapper's own dispatch inputs are kept, so a run it starts queues
    and times out as the wrapper's runs do.
    """
    scripts = [step["with"]["script"] for job in wrapper["jobs"].values() for step in job["steps"] if "script" in step.get("with", {})]
    script = scripts[0] if len(scripts) == 1 else ""
    fields = dict(re.findall(r"(workflow_id|simulator|concurrency_group|timeout_minutes): '([^']+)'", script))
    if fields.get("workflow_id") != "generic.yaml" or "simulator" not in fields:
        return None
    simulators = json.loads(fields["simulator"])
    if not all(s.startswith(EELS) for s in simulators):
        return None
    inputs = generic[True]["workflow_dispatch"]["inputs"]
    return {
        "workflow": "generic.yaml",
        "clients": json.loads(inputs["client"]["default"]),
        "simulators": simulators,
        "client_file": inputs["client_file"]["default"],
        "inputs": {key: fields[key] for key in ("concurrency_group", "timeout_minutes") if key in fields},
        "json_lists": True,
        "quick": False,
        **release_settings(generic),
    }


def watched() -> dict:
    """Return the settings of each watched workflow without a schedule."""
    result = {}
    for path in sorted(WORKFLOWS.glob("hive-*.yaml")):
        workflow = yaml.safe_load(path.read_text())
        if "schedule" not in workflow[True]:
            result[path.name] = settings(path.name, workflow)
    generic = yaml.safe_load((WORKFLOWS / "generic.yaml").read_text())
    for path in sorted(WORKFLOWS.glob("sim-ethereum-eels-*.yaml")):
        wrapper = yaml.safe_load(path.read_text())
        if "schedule" not in wrapper[True] and (config := wrapper_settings(wrapper, generic)):
            result[path.name] = config
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
    if source is None or source[0] not in images.TOKEN_URLS:
        return images.digest(image)
    host, repository = source
    token = images.pull_token(host, repository)
    response = images.registry_api(host, repository, f"manifests/{tag}", token)
    if response is None:
        return None
    manifest = json.load(response)
    if "manifests" in manifest:
        platforms = [m for m in manifest["manifests"] if m.get("platform", {}).get("architecture") == "amd64"]
        manifest = json.load(images.registry_api(host, repository, f"manifests/{(platforms or manifest['manifests'])[0]['digest']}", token))
    config = json.load(images.registry_api(host, repository, f"blobs/{manifest['config']['digest']}", token))
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


def pair_images(config: dict, images_now: dict) -> dict:
    """Return the client and simulator images of each pair a workflow can run.

    Leaves out pairs with an unpublished image, which would only fail to
    start.
    """
    result = {}
    for client in config["clients"]:
        for simulator in config["simulators"]:
            refs = [images_now.get(f"client:{client}", ""), images_now.get(f"simulator:{simulator}", "")]
            if not any(ref.endswith("@") for ref in refs):
                result[f"{client}|{simulator}"] = refs
    return result


def rebuilt(before: list, refs: list) -> bool:
    """Return whether only the client image changed, rebuilt under the same tag."""
    return before[1] == refs[1] and before[0].partition("@")[0] == refs[0].partition("@")[0]


def throttled(config: dict, simulator: str) -> bool:
    """Return whether client rebuilds rerun a simulator at most every FULL_RUN_INTERVAL."""
    return not config["quick"] and simulator not in FAST_SIMULATORS


def refresh_hours(workflows: dict) -> dict:
    """Return the hour of the day, in UTC, each watched workflow refreshes at.

    Spread evenly over the day in name order.
    """
    return {name: index * 24 // len(workflows) for index, name in enumerate(sorted(workflows))}


def last_refresh(hour: int, now: datetime) -> datetime:
    """Return the latest time at or before now that is `hour` o'clock.

    A check that missed it, as when GitHub drops a scheduled run, still
    sees it.
    """
    refresh = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    return refresh if refresh <= now else refresh - timedelta(days=1)


def due(last: dict | None, refs: list, throttle: bool, refresh: datetime, now: datetime) -> bool:
    """Return whether a pair runs on this check, see the module docstring.

    `refresh` is its workflow's last refresh, see `last_refresh`.
    """
    if last is None:
        return True
    ran = datetime.fromisoformat(last["ran"])
    if ran <= refresh - RECENT_RUN:
        return True
    if last["with"] == refs:
        return False
    return not throttle or not rebuilt(last["with"], refs) or now - ran >= FULL_RUN_INTERVAL


def plan(images_now: dict, previous: dict, workflows: dict, now: datetime) -> list:
    """Return the runs due, as (watched workflow, clients, simulators)."""
    runs = []
    hours = refresh_hours(workflows)
    for name, config in workflows.items():
        if name not in previous:
            continue
        pairs = pair_images(config, images_now[name])
        refresh = last_refresh(hours[name], now)
        due_now = {
            key
            for key, refs in pairs.items()
            if due(previous[name].get(key), refs, throttled(config, key.split("|")[1]), refresh, now)
        }
        # Clients due for the same simulators share a run, so a run starts
        # only pairs that are due.
        groups = {}
        for client in config["clients"]:
            simulators = tuple(s for s in config["simulators"] if f"{client}|{s}" in due_now)
            if simulators:
                groups.setdefault(simulators, []).append(client)
        runs += [(name, clients, list(simulators)) for simulators, clients in groups.items()]
    return runs


def record(images_now: dict, previous: dict, workflows: dict, ran: set, now: datetime) -> dict:
    """Return the state after this check.

    A pair that ran, or that a workflow missing from `previous` can run,
    is recorded as run now with its current images. Every other pair
    keeps its previous record, so a change that has to wait stays due.
    """
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {}
    for name, config in workflows.items():
        pairs = pair_images(config, images_now[name])
        before = previous.get(name, {})
        state[name] = {}
        for key in (f"{c}|{s}" for c in config["clients"] for s in config["simulators"]):
            if key in pairs and (name not in previous or (name, key) in ran):
                state[name][key] = {"ran": stamp, "with": pairs[key]}
            elif key in before:
                state[name][key] = before[key]
    return state


def run(config: dict, clients: list, simulators: list) -> tuple:
    """Return the workflow and inputs that run these clients and simulators."""
    lists = json.dumps if config.get("json_lists") else join_list
    return config["workflow"], {**config["inputs"], "client": lists(clients), "simulator": lists(simulators)}


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
    parser.add_argument("--previous", required=True, help="state of the previous check")
    parser.add_argument("--state", required=True, help="file to write the new state to")
    parser.add_argument("--dispatch", action="store_true", help="dispatch the runs")
    parser.add_argument("--now", type=datetime.fromisoformat, help="time of the check (default: now)")
    args = parser.parse_args()

    now = (args.now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    previous = json.loads(Path(args.previous).read_text() or "{}")
    workflows = watched()
    images_now = current(workflows)
    runs = plan(images_now, previous, workflows, now)
    for name in workflows:
        if name not in previous:
            print(f"{name}: recorded")
    ran, failed = set(), False
    for name, clients, simulators in runs:
        workflow, inputs = run(workflows[name], clients, simulators)
        print(f"{name}: {workflow} {inputs}")
        if args.dispatch:
            try:
                dispatch(workflow, inputs)
            except OSError as err:
                # The pairs stay due, so the next check retries them.
                print(f"  dispatch failed: {err}")
                failed = True
                continue
        ran |= {(name, f"{c}|{s}") for c in clients for s in simulators}
    if not runs:
        print("nothing to run")
    state = record(images_now, previous, workflows, ran, now)
    Path(args.state).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
