import importlib.util
import io
import re
import subprocess
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

import yaml

SCRIPT = Path(__file__).resolve().with_name("select_clients.py")
spec = importlib.util.spec_from_file_location("select_clients", SCRIPT)
select_clients = importlib.util.module_from_spec(spec)
spec.loader.exec_module(select_clients)
images = select_clients.images

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"
HUB = "docker.ethquokkaops.io/dh/ethpandaops"
IMAGE = {"client": "besu", "build_args": {"baseimage": f"{HUB}/besu", "tag": "heze-devnet-3"}}
BRANCH = {"client": "reth", "dockerfile": "git", "build_args": {"github": "paradigmxyz/reth", "tag": "heze-devnet-3"}}


def select(clients: list, entries: list, images_found=(), branches_found=()) -> tuple:
    return select_clients.select(
        clients,
        entries,
        lambda image: image in images_found,
        lambda repository, ref: (repository, ref) in branches_found,
    )


class SourceTests(unittest.TestCase):
    def test_image_and_branch_builds(self) -> None:
        self.assertEqual(select_clients.source(IMAGE), ("image", f"{HUB}/besu:heze-devnet-3"))
        self.assertEqual(select_clients.source(BRANCH), ("branch", "paradigmxyz/reth", "heze-devnet-3"))

    def test_unchecked_builds(self) -> None:
        commit = {"dockerfile": "git", "build_args": {"github": "paradigmxyz/reth", "tag": "0b46218"}}
        other_registry = {"build_args": {"baseimage": "quay.io/x/besu", "tag": "main"}}
        for entry in (commit, other_registry, {"client": "besu"}):
            with self.subTest(entry=entry):
                self.assertIsNone(select_clients.source(entry))

    def test_maps_images_to_registries(self) -> None:
        self.assertEqual(images.registry(f"{HUB}/besu"), ("docker-hub", "ethpandaops/besu"))
        self.assertEqual(images.registry("ghcr.io/a/b"), ("ghcr", "a/b"))
        self.assertEqual(images.registry("ubuntu"), ("docker-hub", "library/ubuntu"))
        self.assertIsNone(images.registry("quay.io/x/y"))


def failing(*_: str) -> bool:
    raise select_clients.CheckFailed("rate limited")


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://hub.docker.com", code, "error", {}, None)


class SelectTests(unittest.TestCase):
    def test_keeps_clients_whose_image_or_branch_exists(self) -> None:
        found = select(["besu", "reth"], [IMAGE, BRANCH], {f"{HUB}/besu:heze-devnet-3"}, {("paradigmxyz/reth", "heze-devnet-3")})
        self.assertEqual(found, (["besu", "reth"], [], []))

    def test_skips_clients_without_an_image_or_branch(self) -> None:
        kept, skipped, unchecked = select(["besu", "reth"], [IMAGE, BRANCH])
        self.assertEqual((kept, unchecked), ([], []))
        self.assertEqual([name for name, _ in skipped], ["besu", "reth"])
        self.assertIn("not published", skipped[0][1])
        self.assertIn("no branch or tag heze-devnet-3", skipped[1][1])

    def test_keeps_clients_it_cannot_check(self) -> None:
        self.assertEqual(select(["geth"], [IMAGE]), (["geth"], [], []))

    def test_keeps_clients_whose_lookup_fails(self) -> None:
        kept, skipped, unchecked = select_clients.select(["besu", "reth"], [IMAGE, BRANCH], failing, failing)
        self.assertEqual((kept, skipped), (["besu", "reth"], []))
        self.assertEqual(unchecked, [("besu", "rate limited"), ("reth", "rate limited")])


class LookupTests(unittest.TestCase):
    def setUp(self) -> None:
        images.docker_hub_headers.cache_clear()
        self.addCleanup(images.docker_hub_headers.cache_clear)
        sleep = mock.patch.object(images.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_image_lookup_errors_fail_the_check(self) -> None:
        with mock.patch.object(images, "digest", side_effect=http_error(429)):
            with self.assertRaises(select_clients.CheckFailed):
                select_clients.image_exists(f"{HUB}/besu:main")
        with mock.patch.object(images, "digest", return_value=None):
            self.assertFalse(select_clients.image_exists(f"{HUB}/besu:main"))

    def test_branch_lookup_errors_fail_the_check(self) -> None:
        def ls_remote(code: int):
            return mock.patch.object(
                select_clients.subprocess, "run", return_value=subprocess.CompletedProcess([], code, "", "fatal")
            )

        with ls_remote(128), self.assertRaises(select_clients.CheckFailed):
            select_clients.branch_exists("paradigmxyz/reth", "main")
        with ls_remote(2):
            self.assertFalse(select_clients.branch_exists("paradigmxyz/reth", "main"))

    def test_fetch_retries_errors_but_not_a_missing_image(self) -> None:
        request = images.urllib.request.Request("https://hub.docker.com")
        ok = io.BytesIO(b"{}")
        with mock.patch.object(images.urllib.request, "urlopen", side_effect=[http_error(429), OSError("reset"), ok]) as urlopen:
            self.assertIs(images.fetch(request), ok)
            self.assertEqual(urlopen.call_count, 3)
        with mock.patch.object(images.urllib.request, "urlopen", side_effect=http_error(404)) as urlopen:
            self.assertIsNone(images.fetch(request))
            self.assertEqual(urlopen.call_count, 1)
        with mock.patch.object(images.urllib.request, "urlopen", side_effect=http_error(500)) as urlopen:
            with self.assertRaises(urllib.error.HTTPError):
                images.fetch(request)
            self.assertEqual(urlopen.call_count, images.ATTEMPTS)

    def test_docker_hub_lookups_fall_back_to_anonymous(self) -> None:
        with mock.patch.dict(images.os.environ, {}, clear=True):
            self.assertEqual(images.docker_hub_headers(), {})
        images.docker_hub_headers.cache_clear()
        credentials = {"DOCKERHUB_USERNAME": "ethpandaops", "DOCKERHUB_TOKEN": "token"}
        with mock.patch.dict(images.os.environ, credentials), mock.patch.object(
            images.urllib.request, "urlopen", side_effect=http_error(401)
        ), mock.patch.object(images.sys, "stderr", io.StringIO()):
            self.assertEqual(images.docker_hub_headers(), {})
        images.docker_hub_headers.cache_clear()
        with mock.patch.dict(images.os.environ, credentials), mock.patch.object(
            images.urllib.request, "urlopen", return_value=io.BytesIO(b'{"access_token": "abc"}')
        ):
            self.assertEqual(images.docker_hub_headers(), {"Authorization": "Bearer abc"})


class WorkflowTests(unittest.TestCase):
    """Every dashboard workflow runs only the clients its prepare job selected."""

    def test_dashboards_run_the_selected_clients(self) -> None:
        paths = sorted(WORKFLOWS.glob("hive-*.yaml"))
        self.assertTrue(paths)
        for path in paths:
            workflow = yaml.safe_load(path.read_text())
            with self.subTest(workflow=path.name):
                prepare, test = workflow["jobs"]["prepare"], workflow["jobs"]["test"]
                (step,) = [s for s in prepare["steps"] if s.get("id") == "clients"]
                self.assertEqual(prepare["outputs"]["clients"], "${{ steps.clients.outputs.clients }}")
                self.assertEqual(test["if"], "needs.prepare.outputs.clients != '[]'")
                self.assertEqual(test["strategy"]["matrix"]["client"], "${{ fromJSON(needs.prepare.outputs.clients) }}")
                self.assertEqual(step["env"]["DOCKERHUB_TOKEN"], "${{ secrets.DOCKERHUB_TOKEN }}")
                # The fallback for scheduled runs lists the same clients as the input default.
                fallback = re.search(r"inputs\.client \|\| '([^']+)'", step["env"]["CLIENTS"]).group(1)
                default = workflow[True]["workflow_dispatch"]["inputs"]["client"]["default"]
                self.assertEqual(set(select_clients.split_list(fallback)), set(select_clients.split_list(default)))


if __name__ == "__main__":
    unittest.main()
