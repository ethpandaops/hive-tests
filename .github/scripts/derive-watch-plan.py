"""Derive the image watch plan from the workflow files.

Emits one line per watched image:
  hive|<workflow file>|<hive client>|<registry image:tag>
  generic|generic.yaml|<hive client>|<registry image:tag>
  sim|<eels simulator>|<concurrency group>

Used by watch-client-images.yaml to decide what to poll and dispatch, and
by vet.yaml to fail PRs that break the assumptions this derivation makes
about the workflow files (dispatch input names and JSON defaults).
"""

import glob
import json
import re

import yaml


def inputs(path):
    doc = yaml.safe_load(open(path))
    # YAML 1.1 parses the "on" key as boolean True
    return (doc.get(True) or doc.get("on"))["workflow_dispatch"]["inputs"]


def helper_key(client):
    # hive client name -> client-config helper key
    return {"go-ethereum": "geth", "nimbus-el": "nimbusel"}.get(client, client)


def unwrap(ref):
    # the pull-through mirror serves Docker Hub content
    prefix = "docker.ethquokkaops.io/dh/"
    return ref[len(prefix):] if ref.startswith(prefix) else ref


# Devnet workflows (full and quick): watch each client image at
# the workflow's own common_client_tag, dispatch that workflow.
for wf in sorted(glob.glob(".github/workflows/hive-*.yaml")):
    ins = inputs(wf)
    tag = ins["common_client_tag"]["default"]
    clients = [c.strip().strip('"') for c in ins["client"]["default"].split(",")]
    images = json.loads(ins["client_images"]["default"])
    for c in clients:
        base = unwrap(images[helper_key(c)])
        print(f"hive|{wf.rsplit('/', 1)[-1]}|{c}|{base.rsplit(':', 1)[0]}:{tag}")

# Generic: watch each client image at its default tag,
# dispatch generic.yaml per eels simulator wrapper.
ins = inputs(".github/workflows/generic.yaml")
clients = json.loads(ins["client"]["default"])
images = json.loads(ins["client_config"]["default"])["images"]
for c in clients:
    print(f"generic|generic.yaml|{c}|{unwrap(images[helper_key(c)])}")
for wf in sorted(glob.glob(".github/workflows/sim-ethereum-eels-*.yaml")):
    text = open(wf).read()
    sim = re.search(r"ethereum/eels/([a-z-]+)", text).group(1)
    cg = re.search(r"concurrency_group: '([^']+)'", text).group(1)
    print(f"sim|{sim}|{cg}")
