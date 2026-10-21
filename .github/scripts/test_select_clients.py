import importlib.util
import re
import unittest
from pathlib import Path

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


class SelectTests(unittest.TestCase):
    def test_keeps_clients_whose_image_or_branch_exists(self) -> None:
        found = select(["besu", "reth"], [IMAGE, BRANCH], {f"{HUB}/besu:heze-devnet-3"}, {("paradigmxyz/reth", "heze-devnet-3")})
        self.assertEqual(found, (["besu", "reth"], []))

    def test_skips_clients_without_an_image_or_branch(self) -> None:
        kept, skipped = select(["besu", "reth"], [IMAGE, BRANCH])
        self.assertEqual(kept, [])
        self.assertEqual([name for name, _ in skipped], ["besu", "reth"])
        self.assertIn("not published", skipped[0][1])
        self.assertIn("no branch or tag heze-devnet-3", skipped[1][1])

    def test_keeps_clients_it_cannot_check(self) -> None:
        self.assertEqual(select(["geth"], [IMAGE]), (["geth"], []))


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
                # The fallback for scheduled runs lists the same clients as the input default.
                fallback = re.search(r"inputs\.client \|\| '([^']+)'", step["env"]["CLIENTS"]).group(1)
                default = workflow[True]["workflow_dispatch"]["inputs"]["client"]["default"]
                self.assertEqual(set(select_clients.split_list(fallback)), set(select_clients.split_list(default)))


if __name__ == "__main__":
    unittest.main()
