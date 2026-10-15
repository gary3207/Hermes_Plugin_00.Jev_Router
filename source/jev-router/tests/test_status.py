import importlib.util
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY = {"value": None}

# Stub the two Hermes modules _aa_status touches so the test runs without a Hermes install.
sys.modules["hermes_constants"] = types.SimpleNamespace(get_hermes_home=lambda: Path("/hh"))
sys.modules.setdefault("hermes_cli", types.ModuleType("hermes_cli"))
sys.modules["hermes_cli.config"] = types.SimpleNamespace(get_env_value=lambda k: KEY["value"] if k == "AA_API_KEY" else None)

_spec = importlib.util.spec_from_file_location("jevr_pkg", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(_spec)
sys.modules["jevr_pkg"] = plugin
_spec.loader.exec_module(plugin)


class StatusTest(unittest.TestCase):
    def test_missing_key(self):
        KEY["value"] = None
        st = plugin._aa_status({})
        self.assertFalse(st["aa_key_set"])
        self.assertIn("artificialanalysis.ai", st["help"])
        self.assertIn(str(Path("/hh") / ".env"), st["help"])

    def test_key_ok_and_secret_not_leaked(self):
        KEY["value"] = "secret-123"
        st = plugin._aa_status({"slug": {}})
        self.assertEqual((st["aa_key_set"], st["aa_data"], st["help"]), (True, True, ""))
        self.assertNotIn("secret-123", repr(st))

    def test_key_set_but_fetch_failed(self):
        KEY["value"] = "secret-123"
        st = plugin._aa_status({})
        self.assertIn("조회에 실패", st["help"])
        self.assertNotIn("secret-123", repr(st))


if __name__ == "__main__":
    unittest.main()
