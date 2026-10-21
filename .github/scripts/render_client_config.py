# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "PyYAML==6.0.3",
# ]
# ///

"""
Render the hive client file a workflow passes to hive-github-action.

Reads `.github/configs/hive/<file>` or, when the `CLIENT_CONFIG`
environment variable is non-empty, that inline YAML instead (the
`client_config` dispatch input). The inline YAML replaces the file's
client entries. Each simulator entry of the file still applies unless
the inline YAML has its own entry for that simulator, so testing a
client branch keeps the EELS image tag and build arguments of the run. Fills `${NAME}` placeholders from
`--var NAME=VALUE` first, so a devnet family can keep one client file
whose branch or image tag follows the fixtures release (`--var
DEVNET=bogota-devnet-1`), and fails on a placeholder left unfilled.
The file may also carry simulator entries (`simulator`, `dockerfile`,
`build_args`), which hive's `--config` applies to the simulators a run
selects with `--sim`. Validates the hive config-file shape so a typo
fails here rather than as an obscure hive build error, adds a `GOPROXY` build arg to git builds
of Go clients when the `GOPROXY` environment variable is set, prints
the result, and writes it as the `client_config` step output when
`GITHUB_OUTPUT` is set.
"""

import argparse
import os
import string
import sys
import uuid

import yaml

CONFIG_DIR = ".github/configs/hive"
# Clients whose Dockerfile.git declares ARG GOPROXY.
GOPROXY_CLIENTS = {"go-ethereum", "erigon"}
ALLOWED_KEYS = {"client", "nametag", "dockerfile", "build_args"}
SIMULATOR_KEYS = {"simulator", "dockerfile", "build_args"}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def validate(entries, source: str) -> None:
    """Check the hive config-file shape hive expects."""
    if not isinstance(entries, list) or not entries:
        fail(f"{source}: expected a non-empty list of client entries")
    for index, entry in enumerate(entries):
        where = f"{source}: entry {index}"
        if not isinstance(entry, dict):
            fail(f"{where}: expected a mapping")
        if "simulator" in entry:
            validate_simulator(entry, where)
            continue
        unknown = set(entry) - ALLOWED_KEYS
        if unknown:
            fail(f"{where}: unknown keys {sorted(unknown)}")
        client = entry.get("client")
        if not isinstance(client, str) or not client:
            fail(f"{where}: 'client' must be a non-empty string")
        for key in ("nametag", "dockerfile"):
            if key in entry and not isinstance(entry[key], str):
                fail(f"{where} ({client}): '{key}' must be a string")
        if "build_args" in entry:
            build_args = entry["build_args"]
            if not isinstance(build_args, dict) or not all(
                isinstance(k, str) and isinstance(v, str) for k, v in build_args.items()
            ):
                fail(f"{where} ({client}): 'build_args' must map strings to strings")


def validate_simulator(entry: dict, where: str) -> None:
    """Check a simulator entry of hive's --config file."""
    unknown = set(entry) - SIMULATOR_KEYS
    if unknown:
        fail(f"{where}: unknown keys {sorted(unknown)}")
    simulator = entry["simulator"]
    if not isinstance(simulator, str) or not simulator:
        fail(f"{where}: 'simulator' must be a non-empty string")
    if "dockerfile" in entry and not isinstance(entry["dockerfile"], str):
        fail(f"{where} ({simulator}): 'dockerfile' must be a string")
    build_args = entry.get("build_args", {})
    if not isinstance(build_args, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in build_args.items()
    ):
        fail(f"{where} ({simulator}): 'build_args' must map strings to strings")


def read(path: str) -> str:
    """Return the text of a client file."""
    try:
        with open(path) as handle:
            return handle.read()
    except OSError as err:
        fail(str(err))


def load(source: str, text: str, variables: dict) -> list:
    """Fill the placeholders of a config text, then parse and validate it."""
    text = string.Template(text).safe_substitute(variables)
    unresolved = sorted(string.Template(text).get_identifiers())
    if unresolved:
        fail(f"{source}: unresolved placeholders {unresolved}, pass --var")
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError as err:
        fail(f"{source}: invalid YAML: {err}")
    validate(entries, source)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--file", required=True, help=f"client file name under {CONFIG_DIR}/"
    )
    parser.add_argument(
        "--var",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="fill ${NAME} placeholders in the client file (repeatable)",
    )
    args = parser.parse_args()
    variables = {}
    for assignment in args.var:
        name, separator, value = assignment.partition("=")
        if not separator or not name:
            fail(f"--var expects NAME=VALUE, got {assignment!r}")
        variables[name] = value

    path = os.path.join(CONFIG_DIR, args.file)
    inline = os.environ.get("CLIENT_CONFIG", "").strip()
    if inline:
        source = "client_config input"
        entries = load(source, inline, variables)
        # The inline config replaces the client entries. Each simulator
        # entry of the file still applies unless the inline config has
        # its own entry for that simulator.
        own = {entry["simulator"] for entry in entries if "simulator" in entry}
        entries += [
            entry
            for entry in load(path, read(path), variables)
            if "simulator" in entry and entry["simulator"] not in own
        ]
    else:
        source = path
        entries = load(source, read(path), variables)

    goproxy = os.environ.get("GOPROXY", "")
    if goproxy:
        for entry in entries:
            if entry.get("dockerfile") == "git" and entry.get("client") in GOPROXY_CLIENTS:
                entry.setdefault("build_args", {}).setdefault("GOPROXY", goproxy)

    rendered = yaml.safe_dump(entries, sort_keys=False, default_flow_style=False)
    print(f"client config from {source}:", file=sys.stderr)
    print(rendered)

    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        delimiter = f"EOF_{uuid.uuid4().hex}"
        with open(output, "a") as handle:
            handle.write(f"client_config<<{delimiter}\n{rendered}\n{delimiter}\n")


if __name__ == "__main__":
    main()
