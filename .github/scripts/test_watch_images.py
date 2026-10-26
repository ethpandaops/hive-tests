import importlib.util
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().with_name("watch_images.py")
spec = importlib.util.spec_from_file_location("watch_images", SCRIPT)
watch_images = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch_images)
render_client_config = watch_images.render_client_config

DASHBOARD = {
    "workflow": "hive-x.yaml",
    "inputs": {},
    "clients": ["besu", "geth"],
    "simulators": ["engine", "rlp"],
    "quick": False,
}
QUICK = {**DASHBOARD, "quick": True}
HUB = "docker.ethquokkaops.io/dh/ethpandaops"
GHCR = "ghcr.io/ethereum/execution-specs/hive"
# Midnight, the refresh hour of a lone watched workflow.
START = datetime(2026, 10, 22, tzinfo=timezone.utc)


def images(**refs: str) -> dict:
    """Return the images of one dashboard workflow, keyed as the watcher keys them."""
    return {"hive-x.yaml": {key.replace("_", ":", 1): value for key, value in refs.items()}}


BEFORE = images(client_besu="besu:1@a", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
EVERY_PAIR = (["besu", "geth"], ["engine", "rlp"])


def first_check(then: dict = BEFORE, config: dict = DASHBOARD) -> dict:
    """Return the state the first check at START records."""
    return watch_images.record(then, {}, {"hive-x.yaml": config}, set(), START)


def plan(now: dict, hours: float, config: dict = DASHBOARD, previous: dict | None = None) -> list:
    """Return the (clients, simulators) runs due `hours` after the first check."""
    previous = first_check(config=config) if previous is None else previous
    runs = watch_images.plan(now, previous, {"hive-x.yaml": config}, START + timedelta(hours=hours))
    return [(clients, simulators) for _, clients, simulators in runs]


class WorkflowTests(unittest.TestCase):
    def test_lists_round_trip(self) -> None:
        names = watch_images.split_list('"besu","reth"')
        self.assertEqual(names, ["besu", "reth"])
        self.assertEqual(watch_images.join_list(names), '"besu","reth"')

    def test_reads_what_a_dashboard_runs_by_default(self) -> None:
        workflow = yaml.safe_load((watch_images.WORKFLOWS / "hive-heze.yaml").read_text())
        settings = watch_images.settings("hive-heze.yaml", workflow)
        self.assertEqual(settings["prefix"], "tests-heze-devnet")
        self.assertEqual(settings["devnet"], "heze-devnet-{major}")
        self.assertEqual(settings["client_file"], "heze.yaml")
        self.assertIn("besu", settings["clients"])
        self.assertIn("ethereum/eels/consume-engine", settings["simulators"])
        self.assertFalse(settings["quick"])
        quick = yaml.safe_load((watch_images.WORKFLOWS / "hive-heze-quick.yaml").read_text())
        self.assertTrue(watch_images.settings("hive-heze-quick.yaml", quick)["quick"])

    def test_reads_what_an_eels_wrapper_runs_through_mainnet(self) -> None:
        mainnet = yaml.safe_load((watch_images.WORKFLOWS / "mainnet.yaml").read_text())
        wrapper = yaml.safe_load((watch_images.WORKFLOWS / "sim-ethereum-eels-consume-rlp.yaml").read_text())
        settings = watch_images.wrapper_settings(wrapper, mainnet)
        self.assertEqual(settings["workflow"], "mainnet.yaml")
        self.assertEqual(settings["simulators"], ["ethereum/eels/consume-rlp"])
        self.assertEqual(settings["inputs"], {"concurrency_group": "eels-consume-rlp", "timeout_minutes": "2880"})
        self.assertEqual(settings["prefix"], "tests")
        self.assertIn("besu", settings["clients"])
        self.assertFalse(settings["quick"])

    def test_skips_wrappers_of_other_simulators(self) -> None:
        mainnet = yaml.safe_load((watch_images.WORKFLOWS / "mainnet.yaml").read_text())
        wrapper = yaml.safe_load((watch_images.WORKFLOWS / "sim-ethereum-engine.yaml").read_text())
        self.assertIsNone(watch_images.wrapper_settings(wrapper, mainnet))

    def test_watches_every_eels_wrapper_without_a_schedule(self) -> None:
        watched = watch_images.watched()
        for path in sorted(watch_images.WORKFLOWS.glob("sim-ethereum-eels-*.yaml")):
            scheduled = "schedule" in yaml.safe_load(path.read_text())[True]
            with self.subTest(workflow=path.name):
                self.assertNotEqual(path.name in watched, scheduled)

    def test_only_master_dispatches_and_keeps_the_state(self) -> None:
        workflow = yaml.safe_load((watch_images.WORKFLOWS / "watch-images.yaml").read_text())
        (step,) = [s for s in workflow["jobs"]["watch"]["steps"] if "watch_images.py" in s.get("run", "")]
        self.assertEqual(step["env"]["DISPATCH"], "${{ github.ref == 'refs/heads/master' && '--dispatch' || '' }}")
        self.assertIn("$DISPATCH", step["run"])
        self.assertNotIn("--dispatch", step["run"])
        self.assertIn('[ -n "$DISPATCH" ]', step["run"])

    def test_checks_dispatch_the_next_one_on_master(self) -> None:
        workflow = yaml.safe_load((watch_images.WORKFLOWS / "watch-images.yaml").read_text())
        watch, following = workflow["jobs"]["watch"], workflow["jobs"]["next"]
        self.assertEqual(workflow["env"]["CHECK_INTERVAL"], 3600)
        self.assertEqual(following["needs"], "watch")
        self.assertEqual(following["if"], "${{ !cancelled() && github.ref == 'refs/heads/master' }}")
        self.assertGreater(following["timeout-minutes"] * 60, workflow["env"]["CHECK_INTERVAL"])
        self.assertEqual(following["permissions"], {"actions": "write"})
        # The newest run's wait replaces any older one, so one loop runs.
        self.assertNotEqual(following["concurrency"]["group"], watch["concurrency"]["group"])
        self.assertIs(following["concurrency"]["cancel-in-progress"], True)
        steps = "\n".join(step["run"] for step in following["steps"])
        self.assertIn("CHECK_INTERVAL - ELAPSED", steps)
        self.assertIn("gh workflow run watch-images.yaml --ref master", steps)
        # The cron stays, to restart the loop if it stops.
        self.assertIn("schedule", workflow[True])

    def test_watched_workflows_refresh_at_different_hours(self) -> None:
        hours = watch_images.refresh_hours(watch_images.watched())
        self.assertEqual(len(set(hours.values())), len(hours))
        self.assertTrue(all(0 <= hour < 24 for hour in hours.values()))

    def test_fast_simulators_are_watched(self) -> None:
        simulators = {s for settings in watch_images.watched().values() for s in settings["simulators"]}
        for simulator in watch_images.FAST_SIMULATORS:
            with self.subTest(simulator=simulator):
                self.assertIn(simulator, simulators)

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
        self.assertEqual(plan(BEFORE, 1), [])

    def test_new_workflow_is_only_recorded(self) -> None:
        workflows = {"hive-x.yaml": DASHBOARD}
        self.assertEqual(watch_images.plan(BEFORE, {}, workflows, START), [])
        state = first_check()["hive-x.yaml"]
        self.assertEqual(sorted(state), ["besu|engine", "besu|rlp", "geth|engine", "geth|rlp"])
        self.assertEqual(state["besu|rlp"], {"ran": "2026-10-22T00:00:00Z", "with": ["besu:1@a", "rlp:1@d"]})

    def test_client_rebuild_waits_on_a_full_dashboard(self) -> None:
        now = images(client_besu="besu:1@new", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
        self.assertEqual(plan(now, 11), [])
        self.assertEqual(plan(now, 12), [(["besu"], ["engine", "rlp"])])

    def test_client_rebuild_runs_right_away_on_a_quick_dashboard(self) -> None:
        now = images(client_besu="besu:1@new", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
        self.assertEqual(plan(now, 1, config=QUICK), [(["besu"], ["engine", "rlp"])])

    def test_client_rebuild_runs_fast_simulators_right_away(self) -> None:
        enginex = "ethereum/eels/consume-enginex"
        config = {**DASHBOARD, "simulators": ["engine", enginex]}
        sims = {"simulator:engine": "engine:1@c", f"simulator:{enginex}": "enginex:1@d"}
        then = {"hive-x.yaml": {"client:besu": "besu:1@a", "client:geth": "geth:1@b", **sims}}
        now = {"hive-x.yaml": {"client:besu": "besu:1@new", "client:geth": "geth:1@b", **sims}}
        previous = first_check(then, config)
        self.assertEqual(plan(now, 1, config=config, previous=previous), [(["besu"], [enginex])])
        self.assertEqual(plan(now, 12, config=config, previous=previous), [(["besu"], ["engine", enginex])])

    def test_waiting_rebuild_stays_due(self) -> None:
        now = images(client_besu="besu:1@new", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
        workflows = {"hive-x.yaml": DASHBOARD}
        later = watch_images.record(now, first_check(), workflows, set(), START + timedelta(hours=1))
        self.assertEqual(plan(now, 12, previous=later), [(["besu"], ["engine", "rlp"])])

    def test_new_client_tag_runs_right_away(self) -> None:
        now = images(client_besu="besu:2@e", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
        self.assertEqual(plan(now, 1), [(["besu"], ["engine", "rlp"])])

    def test_new_simulator_release_runs_every_client(self) -> None:
        now = images(client_besu="besu:1@a", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@new")
        self.assertEqual(plan(now, 1), [(["besu", "geth"], ["rlp"])])

    def test_new_release_runs_with_a_waiting_rebuild(self) -> None:
        now = images(client_besu="besu:1@new", client_geth="geth:1@b", simulator_engine="engine:1@new", simulator_rlp="rlp:1@d")
        self.assertEqual(plan(now, 1), [(["besu", "geth"], ["engine"])])

    def test_runs_start_only_due_pairs(self) -> None:
        now = images(client_besu="besu:2@e", client_geth="geth:1@b", simulator_engine="engine:1@new", simulator_rlp="rlp:1@d")
        self.assertEqual(plan(now, 1), [(["besu"], ["engine", "rlp"]), (["geth"], ["engine"])])

    def test_every_pair_runs_daily(self) -> None:
        self.assertEqual(plan(BEFORE, 23), [])
        self.assertEqual(plan(BEFORE, 24), [EVERY_PAIR])
        self.assertEqual(plan(BEFORE, 24, config=QUICK), [EVERY_PAIR])
        # A check that misses the refresh hour runs the refresh at the next one.
        self.assertEqual(plan(BEFORE, 30), [EVERY_PAIR])

    def test_refresh_skips_pairs_that_ran_less_than_12_hours_before(self) -> None:
        workflows = {"hive-x.yaml": DASHBOARD}
        besu = {("hive-x.yaml", "besu|engine"), ("hive-x.yaml", "besu|rlp")}
        for hours, runs in ((12, [EVERY_PAIR]), (13, [(["geth"], ["engine", "rlp"])])):
            with self.subTest(besu_ran=hours):
                state = watch_images.record(BEFORE, first_check(), workflows, besu, START + timedelta(hours=hours))
                self.assertEqual(plan(BEFORE, 24, previous=state), runs)
                self.assertEqual(plan(BEFORE, 48, previous=state), [EVERY_PAIR])

    def test_workflows_refresh_at_different_hours(self) -> None:
        workflows = {"hive-a.yaml": DASHBOARD, "hive-b.yaml": DASHBOARD}
        now = {name: BEFORE["hive-x.yaml"] for name in workflows}
        state = watch_images.record(now, {}, workflows, set(), START)
        refreshed = []
        for hours in range(1, 49):
            check = START + timedelta(hours=hours)
            runs = watch_images.plan(now, state, workflows, check)
            refreshed += [(hours, name) for name, _, _ in runs]
            ran = {(name, f"{c}|{s}") for name, clients, simulators in runs for c in clients for s in simulators}
            state = watch_images.record(now, state, workflows, ran, check)
        self.assertEqual(refreshed, [(12, "hive-b.yaml"), (24, "hive-a.yaml"), (36, "hive-b.yaml"), (48, "hive-a.yaml")])

    def test_unpublished_image_runs_nothing(self) -> None:
        now = images(client_besu="besu:2@", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
        self.assertEqual(plan(now, 1), [])
        self.assertEqual(plan(now, 24), [(["geth"], ["engine", "rlp"])])

    def test_new_devnet_runs_every_client_with_an_image(self) -> None:
        now = images(client_besu="besu:2@", client_geth="geth:2@e", simulator_engine="engine:2@f", simulator_rlp="rlp:2@g")
        self.assertEqual(plan(now, 1), [(["geth"], ["engine", "rlp"])])

    def test_image_appearing_later_runs_its_client(self) -> None:
        then = images(client_besu="besu:2@", client_geth="geth:2@e", simulator_engine="engine:2@f", simulator_rlp="rlp:2@g")
        now = images(client_besu="besu:2@h", client_geth="geth:2@e", simulator_engine="engine:2@f", simulator_rlp="rlp:2@g")
        self.assertEqual(plan(now, 1, previous=first_check(then)), [(["besu"], ["engine", "rlp"])])

    def test_only_pairs_that_ran_are_recorded(self) -> None:
        now = images(client_besu="besu:2@e", client_geth="geth:1@b", simulator_engine="engine:1@c", simulator_rlp="rlp:1@d")
        ran = {("hive-x.yaml", "besu|engine")}
        state = watch_images.record(now, first_check(), {"hive-x.yaml": DASHBOARD}, ran, START + timedelta(hours=1))
        pairs = state["hive-x.yaml"]
        self.assertEqual(pairs["besu|engine"], {"ran": "2026-10-22T01:00:00Z", "with": ["besu:2@e", "engine:1@c"]})
        self.assertEqual(pairs["besu|rlp"], first_check()["hive-x.yaml"]["besu|rlp"])

    def test_mainnet_runs_take_json_lists_and_the_wrapper_inputs(self) -> None:
        config = {**DASHBOARD, "workflow": "mainnet.yaml", "json_lists": True, "inputs": {"concurrency_group": "eels-x"}}
        self.assertEqual(
            watch_images.run(config, ["besu"], ["engine", "rlp"]),
            ("mainnet.yaml", {"concurrency_group": "eels-x", "client": '["besu"]', "simulator": '["engine", "rlp"]'}),
        )
        self.assertEqual(
            watch_images.run(DASHBOARD, ["besu", "geth"], ["rlp"]),
            ("hive-x.yaml", {"client": '"besu","geth"', "simulator": '"rlp"'}),
        )


if __name__ == "__main__":
    unittest.main()
