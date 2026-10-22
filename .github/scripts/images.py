"""
Look up the container images that hive client files and simulators use.

Supports Docker Hub, including registries that mirror it, and ghcr. A
manifest or tag lookup doesn't count as a Docker Hub pull. Docker Hub
lookups authenticate with DOCKERHUB_USERNAME and DOCKERHUB_TOKEN when
both are set, for a higher rate limit than anonymous ones.
"""

import functools
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Registries that mirror Docker Hub.
DOCKER_HUB_MIRRORS = ("docker.ethquokkaops.io/dh/",)
# Attempts at a lookup that fails other than with a 404.
ATTEMPTS = 3
MANIFEST_TYPES = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)


def registry(image: str) -> tuple | None:
    """Return the registry and repository of an image, or None if unsupported."""
    for mirror in DOCKER_HUB_MIRRORS:
        image = image.removeprefix(mirror)
    if image.startswith("ghcr.io/"):
        return "ghcr", image.removeprefix("ghcr.io/")
    if "." in image.split("/")[0]:
        return None
    return "docker-hub", image if "/" in image else f"library/{image}"


def fetch(request: urllib.request.Request):
    """Open a request, or return None when it does not exist.

    Retries any other error, such as a rate limit or an outage, and
    raises it if the last attempt fails too.
    """
    for attempt in range(1, ATTEMPTS + 1):
        try:
            return urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as err:
            if err.code == 404:
                return None
            if attempt == ATTEMPTS:
                raise
        except OSError:
            if attempt == ATTEMPTS:
                raise
        time.sleep(5 * attempt)


@functools.cache
def docker_hub_headers() -> dict:
    """Return the headers that authenticate a Docker Hub API lookup.

    Empty without credentials, or if logging in fails, so lookups fall
    back to anonymous ones.
    """
    username, token = os.environ.get("DOCKERHUB_USERNAME"), os.environ.get("DOCKERHUB_TOKEN")
    if not (username and token):
        return {}
    request = urllib.request.Request(
        "https://hub.docker.com/v2/auth/token",
        method="POST",
        data=json.dumps({"identifier": username, "secret": token}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        access_token = json.load(urllib.request.urlopen(request, timeout=30))["access_token"]
    except (OSError, ValueError, KeyError) as err:
        print(f"Docker Hub login failed, looking up images anonymously: {err!r}", file=sys.stderr)
        return {}
    return {"Authorization": f"Bearer {access_token}"}


def ghcr_token(repository: str) -> str:
    """Return an anonymous pull token for a ghcr repository."""
    url = f"https://ghcr.io/token?scope=repository:{repository}:pull"
    return json.load(fetch(urllib.request.Request(url)))["token"]


def ghcr(repository: str, path: str, token: str, method: str = "GET"):
    """Open a ghcr registry API path, or return None if it does not exist."""
    request = urllib.request.Request(
        f"https://ghcr.io/v2/{repository}/{path}",
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": MANIFEST_TYPES},
    )
    return fetch(request)


def digest(image: str) -> str | None:
    """Return the digest of an `image:tag`, or None if it is not published.

    Also None for a registry this module doesn't support, see `registry`.
    """
    reference, tag = image.rsplit(":", 1)
    source = registry(reference)
    if source is None:
        return None
    kind, repository = source
    if kind == "docker-hub":
        url = f"https://hub.docker.com/v2/repositories/{repository}/tags/{tag}"
        response = fetch(urllib.request.Request(url, headers=docker_hub_headers()))
        return json.load(response)["digest"] if response else None
    response = ghcr(repository, f"manifests/{tag}", ghcr_token(repository), method="HEAD")
    return response.headers["Docker-Content-Digest"] if response else None
