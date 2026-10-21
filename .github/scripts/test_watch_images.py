import importlib.util
import unittest
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().with_name("watch_images.py")
spec = importlib.util.spec_from_file_location("watch_images", SCRIPT)
watch_images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch_images)
render_client_config = watch_images.render_client_config

DASHBOARD = {"clients": ["besu", "geth"], "simulators": ["engine", "rlp"]}
HUB = "docker.ethquokkaops.io/dh/ethpandaops"
GHCR = "ghcr.io/ethereum/execution-specs/hive"


def state(**images: str) -> dict:
    """Return the images of one dashboard workflow, keyed as the watcher keys them."""
    return {"hive-x.yaml": {key.replace("_", ":", 1): value for key, value in images.items()}}


BEFORE = state(client_besu="besu:1@a", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")


def plan(now: dict) -> list:
    return watch_images.plan(now, BEFORE, {"hive-x.yaml": DASHBOARD})


class WorkflowTests(unittest.TestCase):
    def test_lists_round_trip(self) -> None:
        names = watch_images.split_list('"besu","reth"')
        self.assertEqual(names, ["besu", "reth"])
        self.assertEqual(watch_images.join_list(names), '"besu","reth"')

    def test_reads_what_a_dashboard_runs_by_default(self) -> None:
        workflow = yaml.safe_load((watch_images.WORKFLOWS / "hive-heze.yaml").read_text())
        settings = watch_images.settings(workflow)
        self.assertEqual(settings["prefix"], "tests-heze-devnet")
        self.assertEqual(settings["devnet"], "heze-devnet-{major}")
        self.assertEqual(settings["client_file"], "heze.yaml")
        self.assertIn("besu", settings["clients"])
        self.assertIn("ethereum/eels/consume-engine", settings["simulators"])

    def test_watches_every_dashboard_without_a_schedule(self) -> None:
        watched = watch_images.watched()
        for path in sorted(watch_images.WORKFLOWS.glob("hive-*.yaml")):
            scheduled = "schedule" in yaml.safe_load(path.read_text())[True]
            with self.subTest(workflow=path.name):
                self.assertNotEqual(path.name in watched, scheduled)
        self.assertIn("hive-heze-quick.yaml", watched)
        for name, settings in watched.items():
            with self.subTest(workflow=name):
                self.assertTrue((watch_images.CONFIG_DIR / settings["client_file"]).is_file())


class ImageTests(unittest.TestCase):
    def test_reads_the_rendered_client_file(self) -> None:
        path = watch_images.CONFIG_DIR / "heze.yaml"
        entries = render_client_config.load(
            str(path), path.read_text(), {"DEVNET": "heze-devnet-3", "EELS_IMAGE_TAG": "heze-devnet-3"}
        )
        images = watch_images.image_refs(entries, ["besu"], ["ethereum/eels/consume-engine"])
        self.assertEqual(
            images,
            {
                "client:besu": f"{HUB}/besu:heze-devnet-3-linux-amd64",
                "simulator:ethereum/eels/consume-engine": f"{GHCR}/consume-engine:heze-devnet-3",
            },
        )

    def test_skips_source_builds(self) -> None:
        entries = [
            {"client": "besu", "dockerfile": "git", "build_args": {"github": "x/besu", "tag": "main"}},
            {"simulator": "ethereum/eels/consume-rlp", "dockerfile": "git", "build_args": {"tag": "v1"}},
        ]
        self.assertEqual(watch_images.image_refs(entries, ["besu"], ["ethereum/eels/consume-rlp"]), {})

    def test_reads_the_release_an_eels_image_carries(self) -> None:
        def config(**labels: str) -> dict:
            return {"config": {"Labels": {f"org.ethereum.eest.{k.replace('_', '-')}": v for k, v in labels.items()}}}

        self.assertEqual(watch_images.eels_release(config(fixtures_release="tests@v21.0.1")), "tests@v21.0.1")
        self.assertEqual(watch_images.eels_release(config(tests_release="tests-heze-devnet@v3.0.0")), "tests-heze-devnet@v3.0.0")
        self.assertIsNone(watch_images.eels_release(config()))
        self.assertIsNone(watch_images.eels_release({"config": {"Labels": None}}))

class PlanTests(unittest.TestCase):
    def test_nothing_changed(self) -> None:
        self.assertEqual(plan(BEFORE), [])

    def test_new_workflow_is_only_recorded(self) -> None:
        self.assertEqual(watch_images.plan(BEFORE, {}, {"hive-x.yaml": DASHBOARD}), [])

    def test_new_client_image_runs_that_client(self) -> None:
        now = state(client_besu="besu:1@new", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
        self.assertEqual(plan(now), [("hive-x.yaml", {"client": '"besu"', "simulator": '"engine","rlp"'})])

    def test_new_simulator_image_runs_every_client(self) -> None:
        now = state(client_besu="besu:1@a", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@new")
        self.assertEqual(plan(now), [("hive-x.yaml", {"client": '"besu","geth"', "simulator": '"rlp"'})])

    def test_client_and_simulator_changes_never_overlap(self) -> None:
        now = state(client_besu="besu:1@new", client_geth="geth:1@b", simulator_engine="engine:1@new", simulator_rlp="rlp:1@d")
        self.assertEqual(
            plan(now),
            [
                ("hive-x.yaml", {"client": '"besu","geth"', "simulator": '"engine"'}),
                ("hive-x.yaml", {"client": '"besu"', "simulator": '"rlp"'}),
            ],
        )

    def test_unpublished_image_runs_nothing(self) -> None:
        now = state(client_besu="besu:2@", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
        self.assertEqual(plan(now), [])

    def test_new_devnet_runs_every_client_with_an_image(self) -> None:
        now = state(client_besu="besu:2@", client_geth="geth:2@e", simulator_engine="engine:2@f", simulator_rlp="rlp:2@g")
        self.assertEqual(plan(now), [("hive-x.yaml", {"client": '"geth"', "simulator": '"engine","rlp"'})])

    def test_image_appearing_later_runs_its_client(self) -> None:
        before = state(client_besu="besu:2@", client_geth="geth:2@e", simulator_engine="engine:2@f", simulator_rlp="rlp:2@g")
        now = state(client_besu="besu:2@h", client_geth="geth:2@e", simulator_engine="engine:2@f", simulator_rlp="rlp:2@g")
        self.assertEqual(
            watch_images.plan(now, before, {"hive-x.yaml": DASHBOARD}),
            [("hive-x.yaml", {"client": '"besu"', "simulator": '"engine","rlp"'})],
        )


if __name__ == "__main__":
    unittest.main()
