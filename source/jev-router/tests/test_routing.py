import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.modules.setdefault("hermes_constants", types.SimpleNamespace(get_hermes_home=lambda: Path("/hh")))
sys.modules.setdefault("hermes_cli", types.ModuleType("hermes_cli"))
sys.modules.setdefault("hermes_cli.config", types.SimpleNamespace(get_env_value=lambda k: None))

_spec = importlib.util.spec_from_file_location("jevr_pkg2", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)])
plugin = importlib.util.module_from_spec(_spec)
sys.modules["jevr_pkg2"] = plugin
_spec.loader.exec_module(plugin)


class FakeLifecycle:
    def __init__(self):
        self.launched, self.waited = [], []

    def launch(self, req):
        if req["model"] == "boom":
            raise ValueError("no creds")
        self.launched.append(req)
        return types.SimpleNamespace(provider=req["provider"], model=req["model"])

    def wait(self, h):
        assert len(self.launched) == self.expected, "all children must launch before the first wait"
        self.waited.append(h)

    def result(self, h):
        return types.SimpleNamespace(handle=h, terminal_state=types.SimpleNamespace(value="completed"),
                                     error_message=None, summary=f"done on {h.model}")


class RoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()) / "candidates.json"
        plugin._config_path = lambda: self.tmp

    def save(self, *models):
        self.tmp.write_text(json.dumps({"candidates": [{"provider": "anthropic", "model": m} for m in models]}))

    def test_guard_blocks_spawn_only_when_routing_set_up(self):
        self.assertIsNone(plugin._route_guard(tool_name="delegate_task", args={"tasks": [{"goal": "x"}]}))
        self.save("claude-haiku-5-5")
        block = plugin._route_guard(tool_name="delegate_task", args={"tasks": [{"goal": "x"}]})
        self.assertEqual(block["action"], "block")
        self.assertIn("jev_delegate", block["message"])
        self.assertIsNone(plugin._route_guard(tool_name="delegate_task", args={"action": "list"}))
        self.assertIsNone(plugin._route_guard(tool_name="terminal", args={}))

    def test_batch_runs_in_parallel_and_keeps_order(self):
        self.save("claude-haiku-5-5", "claude-opus-5-5", "boom")
        svc = FakeLifecycle()
        svc.expected = 2
        run = plugin._make_delegate(types.SimpleNamespace(subagent_lifecycle=svc))
        out = json.loads(run({"tasks": [
            {"goal": "a", "choice": "anthropic/claude-haiku-5-5", "confidence": 0.8},
            {"goal": "b", "choice": "openai/not-allowed"},
            {"goal": "c", "choice": "anthropic/claude-opus-5-5"},
            {"goal": "d", "choice": "anthropic/boom"},
        ]}))["results"]
        self.assertEqual([r.get("ran_on", {}).get("model") for r in out],
                         ["claude-haiku-5-5", None, "claude-opus-5-5", None])
        self.assertIn("not a saved candidate", out[1]["error"])
        self.assertIn("launch failed", out[3]["error"])

    def test_single_task_shape_unchanged(self):
        self.save("claude-haiku-5-5")
        svc = FakeLifecycle()
        svc.expected = 1
        run = plugin._make_delegate(types.SimpleNamespace(subagent_lifecycle=svc))
        out = json.loads(run({"goal": "a", "choice": "anthropic/claude-haiku-5-5"}))
        self.assertEqual(out["ran_on"]["model"], "claude-haiku-5-5")
        self.assertEqual(out["route"]["by"], "jev choice")


if __name__ == "__main__":
    unittest.main()
