from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "spec"))
import RunBuildDiff as runner


class RunnerTests(unittest.TestCase):
    def test_empty_output_missing_inputs_and_extra_outputs_fail(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            with self.assertRaises(ValueError):
                runner.validate_outputs(p, ["one.xml"])
            (p / "one.xml.build").write_text("<PathOfBuilding><Build/></PathOfBuilding>")
            with self.assertRaises(ValueError):
                runner.validate_outputs(p, ["one.xml"])
            (p / "one.xml.build").write_text('<PathOfBuilding><Build><PlayerStat stat="Life" value="123"/></Build></PathOfBuilding>')
            runner.validate_outputs(p, ["one.xml"])
            self.assertEqual(runner.saved_stats(p / "one.xml.build"), {("PlayerStat", "Life"): "123"})
            (p / "extra.build").write_text("extra")
            with self.assertRaises(ValueError):
                runner.validate_outputs(p, ["one.xml"])

    def test_subprocess_failure_and_timeout_propagate(self):
        with self.assertRaises(subprocess.CalledProcessError):
            runner.run([sys.executable, "-c", "raise SystemExit(7)"])
        with patch.object(runner.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 1)):
            with self.assertRaises(subprocess.TimeoutExpired):
                runner.run(["test"], timeout=1)

    def test_missing_corpus_is_not_implicit_fixtures_mode(self):
        result = subprocess.run([sys.executable, str(Path(runner.__file__)), "--base", "HEAD", "--head", "HEAD", "--output", "unused"], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"choose --corpus or explicit --fixtures-only", result.stderr)

    def test_both_runtime_sources_are_readonly_and_outputs_writable(self):
        self.assertIn("readonly", runner.docker_mount(Path("source"), "/workdir")[1])
        self.assertNotIn("readonly", runner.docker_mount(Path("output"), "/outputs", False)[1])


if __name__ == "__main__":
    unittest.main()
