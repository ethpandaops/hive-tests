"""Derive the image watch plan from the workflow files.

Emits one line per watched image:
  hive|<workflow file>|<hive client>|<registry image:tag>
  generic|generic.yaml|<hive client>|<registry image:tag>
  sim|<eels simulator>|<concurrency group>

and one line per workflow for its non-client test content (a change in any
field re-dispatches the workflow for every client; a workflow whose branch
or fixtures do not exist yet is skipped entirely until they do):
  content|<workflow file>|<eels branch>|<fixtures url>|<fingerprint>

The fingerprint covers the test-relevant configuration: the env blocks
(simulator flags, fixtures, timestamps — infra keys like S3 paths
excluded) and the default simulator list. Client lists and images are
excluded (covered per-client by the image watch), as is hive_version.

Used by watch-client-images.yaml to decide what to poll and dispatch, and
by vet.yaml to fail PRs that break the assumptions this derivation makes
about the workflow files (dispatch input names and JSON defaults).
"""

import glob
import hashlib
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


INFRA_ENV_PREFIXES = ("S3_", "INSTALL_", "GOPROXY")


def content(path, extra=()):
    # the eels branch/fixtures the sims build from, plus a fingerprint of
    # the rest of the test-relevant configuration
    doc = yaml.safe_load(open(path))
    env = dict(doc.get("env") or {})
    env.update((doc.get("jobs") or {}).get("test", {}).get("env") or {})
    branch = env.get("EELS_BUILD_ARG_BRANCH", "")
    fixtures = env.get("EELS_BUILD_ARG_FIXTURES", "")
    tested = {k: v for k, v in env.items()
              if not k.startswith(INFRA_ENV_PREFIXES)}
    sims = inputs(path).get("simulator", {}).get("default", "")
    fingerprint = hashlib.sha256(
        json.dumps([tested, sims, list(extra)], sort_keys=True).encode()
    ).hexdigest()[:16]
    name = path.rsplit("/", 1)[-1]
    return f"content|{name}|{branch}|{fixtures}|{fingerprint}"


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
    print(content(wf))

# Generic: watch each client image at its default tag,
# dispatch generic.yaml per eels simulator wrapper.
ins = inputs(".github/workflows/generic.yaml")
clients = json.loads(ins["client"]["default"])
images = json.loads(ins["client_config"]["default"])["images"]
for c in clients:
    print(f"generic|generic.yaml|{c}|{unwrap(images[helper_key(c)])}")
sims = []
for wf in sorted(glob.glob(".github/workflows/sim-ethereum-eels-*.yaml")):
    text = open(wf).read()
    sim = re.search(r"ethereum/eels/([a-z-]+)", text).group(1)
    cg = re.search(r"concurrency_group: '([^']+)'", text).group(1)
    sims.append((sim, cg))
# the eels wrappers define which simulators generic dispatches run, so
# adding or editing one is a content change for generic
print(content(".github/workflows/generic.yaml", extra=sims))
for sim, cg in sims:
    print(f"sim|{sim}|{cg}")
