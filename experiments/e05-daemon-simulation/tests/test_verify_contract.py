import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]


class ContractVerifierTests(unittest.TestCase):
    def copy_contract(self, destination: Path) -> tuple[Path, Path]:
        repository = destination / "repo"
        experiment = repository / "experiments" / "e05-daemon-simulation"
        experiment.parent.mkdir(parents=True)
        shutil.copytree(EXPERIMENT_ROOT, experiment, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        bindings = json.loads((EXPERIMENT_ROOT / "fixture-bindings.json").read_text(encoding="utf-8"))
        for binding in bindings["bindings"]:
            source = REPOSITORY_ROOT / binding["path"]
            target = repository / binding["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return repository, experiment

    def run_verifier(self, repository: Path, experiment: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "python3",
                str(experiment / "scripts" / "verify_contract.py"),
                "--experiment-root",
                str(experiment),
                "--repository-root",
                str(repository),
            ],
            check=False,
            capture_output=True,
            text=True,
        )

    def refresh_hashes(self, experiment: Path) -> None:
        manifest_path = experiment / "frozen-artifacts.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for artifact in manifest["artifacts"]:
            artifact["sha256"] = hashlib.sha256((experiment / artifact["path"]).read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        (experiment / "protocol.sha256").write_text(f"{digest}  frozen-artifacts.json\n", encoding="utf-8")

    def mutate_json(self, experiment: Path, name: str, mutation) -> None:
        path = experiment / name
        document = json.loads(path.read_text(encoding="utf-8"))
        mutation(document)
        path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        self.refresh_hashes(experiment)

    def test_accepted_contract_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, experiment = self.copy_contract(Path(temporary))
            result = self.run_verifier(repository, experiment)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Phase A contract verified", result.stdout)

    def test_phase_b_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, experiment = self.copy_contract(Path(temporary))
            (experiment / "simulator.py").write_text("raise SystemExit('not Phase A')\n", encoding="utf-8")
            result = self.run_verifier(repository, experiment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Phase B artifact is forbidden", result.stderr)

    def test_threshold_relaxation_is_rejected_even_when_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, experiment = self.copy_contract(Path(temporary))
            self.mutate_json(
                experiment,
                "thresholds.json",
                lambda document: document["safety"].update({"capacity_violation_count_max": 1}),
            )
            result = self.run_verifier(repository, experiment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("frozen safety thresholds changed", result.stderr)

    def test_workload_drift_is_rejected_even_when_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, experiment = self.copy_contract(Path(temporary))
            self.mutate_json(
                experiment,
                "workload.json",
                lambda document: document.update({"primary_agent_count": 19}),
            )
            result = self.run_verifier(repository, experiment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("primary_agent_count must be 20", result.stderr)

    def test_fixture_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, experiment = self.copy_contract(Path(temporary))
            fixture = repository / "fixtures" / "w2" / "graph.json"
            fixture.write_text(fixture.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            result = self.run_verifier(repository, experiment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("live fixture digest mismatch", result.stderr)

    def test_extra_contract_section_is_rejected_even_when_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, experiment = self.copy_contract(Path(temporary))
            self.mutate_json(
                experiment,
                "contract.json",
                lambda document: document.update({"result": "premature"}),
            )
            result = self.run_verifier(repository, experiment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("extra=['result']", result.stderr)

    def test_selected_branch_is_rejected_even_when_rehashed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repository, experiment = self.copy_contract(Path(temporary))
            self.mutate_json(
                experiment,
                "decision-matrix.json",
                lambda document: document.update({"selected_branch": "full-daemon"}),
            )
            result = self.run_verifier(repository, experiment)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("selected_branch must remain null", result.stderr)


if __name__ == "__main__":
    unittest.main()
