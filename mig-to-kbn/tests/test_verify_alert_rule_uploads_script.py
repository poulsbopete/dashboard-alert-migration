import importlib.util
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "scripts" / "verify_alert_rule_uploads.py"


class VerifyAlertRuleUploadsScriptTests(unittest.TestCase):
    def test_script_prefers_local_checkout_over_earlier_sys_path_package(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_root = pathlib.Path(tmpdir)
            fake_pkg = fake_root / "observability_migration" / "targets" / "kibana"
            fake_pkg.mkdir(parents=True)
            (fake_root / "observability_migration" / "__init__.py").write_text("", encoding="utf-8")
            (fake_root / "observability_migration" / "targets" / "__init__.py").write_text("", encoding="utf-8")
            (fake_root / "observability_migration" / "targets" / "kibana" / "__init__.py").write_text(
                "",
                encoding="utf-8",
            )
            (fake_pkg / "alerting.py").write_text(
                "def create_rule(*args, **kwargs):\n"
                "    return {}\n",
                encoding="utf-8",
            )

            original_sys_path = list(sys.path)
            removed_modules = {
                name: sys.modules.pop(name)
                for name in list(sys.modules)
                if name == "observability_migration" or name.startswith("observability_migration.")
            }
            try:
                sys.path = [str(fake_root), *original_sys_path]
                spec = importlib.util.spec_from_file_location("verify_alert_rule_uploads_script", SCRIPT_PATH)
                module = importlib.util.module_from_spec(spec)
                assert spec.loader is not None
                spec.loader.exec_module(module)
                imported_alerting = sys.modules["observability_migration.targets.kibana.alerting"]
            finally:
                sys.path = original_sys_path
                for name in list(sys.modules):
                    if name == "observability_migration" or name.startswith("observability_migration."):
                        sys.modules.pop(name, None)
                sys.modules.update(removed_modules)

        self.assertTrue(callable(module.main))
        self.assertEqual(pathlib.Path(imported_alerting.__file__).resolve(), ROOT / "observability_migration/targets/kibana/alerting.py")
        self.assertIs(module.create_rule, imported_alerting.create_rule)


if __name__ == "__main__":
    unittest.main()
