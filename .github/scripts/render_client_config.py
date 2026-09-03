"""
Render the hive client file a workflow passes to hive-github-action.

Reads `.github/configs/hive/<file>` or, when the `CLIENT_CONFIG`
environment variable is non-empty, that inline YAML instead (the
`client_config` dispatch input). Validates the hive client-file shape so
a typo fails here rather than as an obscure hive build error, adds a
`GOPROXY` build arg to git builds of Go clients when the `GOPROXY`
environment variable is set, prints the result, and writes it as the
`client_config` step output when `GITHUB_OUTPUT` is set.
"""

import argparse
import os
import sys
import uuid

import yaml

CONFIG_DIR = ".github/configs/hive"
# Clients whose Dockerfile.git declares ARG GOPROXY.
GOPROXY_CLIENTS = {"go-ethereum", "erigon"}
ALLOWED_KEYS = {"client", "nametag", "dockerfile", "build_args"}


def fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def validate(entries, source: str) -> None:
    """Check the hive client-file shape hive expects."""
    if not isinstance(entries, list) or not entries:
        fail(f"{source}: expected a non-empty list of client entries")
    for index, entry in enumerate(entries):
        where = f"{source}: entry {index}"
        if not isinstance(entry, dict):
            fail(f"{where}: expected a mapping")
        unknown = set(entry) - ALLOWED_KEYS
        if unknown:
            fail(f"{where}: unknown keys {sorted(unknown)}")
        client = entry.get("client")
        if not isinstance(client, str) or not client:
            fail(f"{where}: 'client' must be a non-empty string")
        args = entry.get("build_args")
        if not isinstance(args, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in args.items()
        ):
            fail(f"{where} ({client}): 'build_args' must map strings to strings")
        if entry.get("dockerfile") == "git":
            required = {"github", "tag"}
        elif "dockerfile" not in entry:
            required = {"baseimage", "tag"}
        else:
            required = {"tag"}
        missing = required - set(args)
        if missing:
            fail(f"{where} ({client}): build_args missing {sorted(missing)}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--file", required=True, help=f"client file name under {CONFIG_DIR}/"
    )
    args = parser.parse_args()

    inline = os.environ.get("CLIENT_CONFIG", "").strip()
    if inline:
        source, text = "client_config input", inline
    else:
        source = os.path.join(CONFIG_DIR, args.file)
        try:
            with open(source) as handle:
                text = handle.read()
        except OSError as err:
            fail(str(err))
    try:
        entries = yaml.safe_load(text)
    except yaml.YAMLError as err:
        fail(f"{source}: invalid YAML: {err}")
    validate(entries, source)

    goproxy = os.environ.get("GOPROXY", "")
    if goproxy:
        for entry in entries:
            if entry.get("dockerfile") == "git" and entry["client"] in GOPROXY_CLIENTS:
                entry["build_args"].setdefault("GOPROXY", goproxy)

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
