import importlib.util
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("router", Path(__file__).resolve().parents[1] / "router.py")
router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(router)

C = [
    {"provider": "a", "model": "light", "tier": 1},
    {"provider": "b", "model": "coder", "tier": 2, "tasks": ["coding"]},
    {"provider": "a", "model": "std", "tier": 2},
    {"provider": "a", "model": "top", "tier": 3},
]


class RouteTest(unittest.TestCase):
    def pick(self, cands, *a):
        return router.route(cands, *a)[0]["model"]

    def test_tiers(self):
        self.assertEqual(self.pick(C, "research", 1, False, 0.9), "light")
        self.assertEqual(self.pick(C, "research", 3, False, 0.9), "std")
        self.assertEqual(self.pick(C, "research", 5, False, 0.9), "top")

    def test_task_preference_and_escalation(self):
        self.assertEqual(self.pick(C, "coding", 3, False, 0.9), "coder")
        self.assertEqual(self.pick(C, "writing", 1, True, 0.9), "top")
        self.assertEqual(self.pick(C, "writing", 2, False, 0.4), "std")

    def test_missing_tier_prefers_higher_then_lower(self):
        only_low_high = [C[0], C[3]]
        self.assertEqual(self.pick(only_low_high, "data", 3, False, 0.9), "top")
        self.assertEqual(self.pick([C[0]], "data", 5, False, 0.9), "light")

    def test_empty(self):
        with self.assertRaises(ValueError):
            router.route([], "coding", 3, False, 0.9)

    def test_validate(self):
        avail = {"a": ["light", "std", "top"], "b": ["coder"]}
        self.assertEqual(router.validate(C, avail), [])
        bad = router.validate([{"provider": "x", "model": "m", "tier": 4, "tasks": ["nope"]}], avail)
        self.assertEqual(len(bad), 3)

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "candidates.json"
            self.assertEqual(router.load(p), [])
            router.save(p, C)
            self.assertEqual(router.load(p), C)

    def test_parse_child(self):
        self.assertEqual(router.parse_child("NEEDS_INPUT: which branch?"),
                         {"status": "needs_input", "question": "which branch?"})
        self.assertEqual(router.parse_child(" done "), {"status": "done", "result": "done"})


if __name__ == "__main__":
    unittest.main()
