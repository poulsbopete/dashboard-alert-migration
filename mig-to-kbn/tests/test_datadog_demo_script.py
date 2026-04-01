import pathlib
import subprocess
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
DATADOG_DEMO_SCRIPT = ROOT / "scripts" / "run_datadog_demo.sh"


def _run_datadog_demo(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(DATADOG_DEMO_SCRIPT), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )


class DatadogDemoScriptTests(unittest.TestCase):
    def test_help_lists_local_and_serverless_targets(self):
        result = _run_datadog_demo("--help")

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertIn("--target", result.stdout)
        self.assertIn("local", result.stdout)
        self.assertIn("serverless", result.stdout)

    def test_serverless_target_rejects_local_lab_flags(self):
        result = _run_datadog_demo("--target", "serverless", "--start-lab")

        self.assertEqual(result.returncode, 1)
        self.assertIn("--start-lab is only valid with --target local", result.stderr)


if __name__ == "__main__":
    unittest.main()
