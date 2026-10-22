import unittest
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / "workflows"
HIVE_ACTION = "ethpandaops/hive-github-action@"
GITHUB_SCRIPT = "actions/github-script@"


def hive_steps(job: dict) -> list:
    """Return the steps of a job that run the hive action."""
    return [step for step in job.get("steps", []) if step.get("uses", "").startswith(HIVE_ACTION)]


def test_jobs(workflow: dict) -> list:
    """Return the jobs of a workflow that run hive tests."""
    return [
        name
        for name, job in workflow["jobs"].items()
        if any(not step.get("with", {}).get("skip_tests") for step in hive_steps(job))
    ]


def index_updates(job: dict) -> list:
    """Return the indexes of the steps of a job that dispatch generate-index."""
    return [
        index
        for index, step in enumerate(job["steps"])
        if step.get("uses", "").startswith(GITHUB_SCRIPT) and "generate-index.yaml" in step["with"]["script"]
    ]


class IndexUpdateTests(unittest.TestCase):
    """Every job that runs hive adds its results to the index through generate-index."""

    def setUp(self) -> None:
        self.workflows = {
            path.name: workflow
            for path in sorted(WORKFLOWS.glob("*.yaml"))
            if test_jobs(workflow := yaml.safe_load(path.read_text()))
        }

    def test_hive_workflows_are_found(self) -> None:
        self.assertIn("generic.yaml", self.workflows)
        self.assertIn("hive-heze-quick.yaml", self.workflows)

    def test_test_jobs_skip_the_index(self) -> None:
        for name, workflow in self.workflows.items():
            for job in test_jobs(workflow):
                for step in hive_steps(workflow["jobs"][job]):
                    with self.subTest(workflow=name, job=job):
                        self.assertIs(step["with"].get("website_index_generation"), False)

    def test_test_jobs_dispatch_an_index_update_for_their_path(self) -> None:
        for name, workflow in self.workflows.items():
            for job_name in test_jobs(workflow):
                with self.subTest(workflow=name, job=job_name):
                    job = workflow["jobs"][job_name]
                    updates = index_updates(job)
                    self.assertEqual(len(updates), 1, "expected one index update step")
                    (update,) = updates
                    hive = job["steps"].index(hive_steps(job)[0])
                    self.assertGreater(update, hive, "index update runs before the hive action")
                    step = job["steps"][update]
                    # Only after the hive action uploaded results.
                    self.assertEqual(step["if"], "${{ !cancelled() && env.RUN_SUCCESS == 'true' }}")
                    self.assertIn("'s3-path': process.env.S3_PATH", step["with"]["script"])
                    self.assertIn("'s3-bucket': process.env.S3_BUCKET", step["with"]["script"])
                    self.assertIn("S3_PATH", workflow["env"])
                    self.assertIn("S3_BUCKET", workflow["env"])

    def test_generate_index_queues_updates_per_path(self) -> None:
        workflow = yaml.safe_load((WORKFLOWS / "generate-index.yaml").read_text())
        # PyYAML reads the `on` key as True.
        inputs = workflow[True]["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"s3-bucket", "s3-path", "full"})
        concurrency = workflow["jobs"]["generate-index"]["concurrency"]
        self.assertIn("inputs.s3-path", concurrency["group"])
        # Queued rather than cancelled, so a running update always finishes.
        self.assertIs(concurrency["cancel-in-progress"], False)


if __name__ == "__main__":
    unittest.main()
