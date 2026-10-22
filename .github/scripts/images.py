"""
Look up the container images that hive client files and simulators use.

Reads ghcr and the Harbor mirror of Docker Hub that hive pulls the
client images from through their registry API, and Docker Hub itself
through its tag API. A manifest or tag lookup doesn't count as a Docker
Hub pull. Docker Hub lookups authenticate with DOCKERHUB_USERNAME and
DOCKERHUB_TOKEN when both are set, for a higher rate limit than
anonymous ones.
"""

import functools
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Registries read through their registry API, with the URL of an
# anonymous pull token for a repository. The mirror serves a pushed tag
# as soon as Docker Hub does, while Docker Hub's tag API can lag it by up
# to a minute.
TOKEN_URLS = {
    "ghcr.io": "https://ghcr.io/token?scope=repository:{repository}:pull",
    "docker.ethquokkaops.io": "https://docker.ethquokkaops.io/service/token?service=harbor-registry&scope=repository:{repository}:pull",
}
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
    """Return the registry and repository of an image, or None if unsupported.

    The registry is a host of TOKEN_URLS, or `docker.io` for Docker Hub.
    """
    host, _, repository = image.partition("/")
    if host in TOKEN_URLS:
        return host, repository
    if "." in host:
        return None
    return "docker.io", image if repository else f"library/{image}"


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


def pull_token(host: str, repository: str) -> str:
    """Return an anonymous pull token for a repository in a registry of TOKEN_URLS."""
    url = TOKEN_URLS[host].format(repository=repository)
    return json.load(fetch(urllib.request.Request(url)))["token"]


def registry_api(host: str, repository: str, path: str, token: str, method: str = "GET"):
    """Open a registry API path, or return None if it does not exist."""
    request = urllib.request.Request(
        f"https://{host}/v2/{repository}/{path}",
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
    host, repository = source
    if host == "docker.io":
        url = f"https://hub.docker.com/v2/repositories/{repository}/tags/{tag}"
        response = fetch(urllib.request.Request(url, headers=docker_hub_headers()))
        return json.load(response)["digest"] if response else None
    response = registry_api(host, repository, f"manifests/{tag}", pull_token(host, repository), method="HEAD")
    return response.headers["Docker-Content-Digest"] if response else None
