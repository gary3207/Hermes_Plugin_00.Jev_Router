import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_spec = importlib.util.spec_from_file_location("router", Path(__file__).resolve().parents[1] / "router.py")
router = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(router)

AA = {
    "claude-opus-5-5-medium": {"name": "Claude Opus 5.5 (Medium)", "evaluations": {
        "artificial_analysis_intelligence_index": 51.2, "artificial_analysis_coding_index": None,
        "artificial_analysis_engineering_index": 53.7}, "pricing": {"price_1m_input_tokens": 4, "price_1m_output_tokens": 20}},
    "gpt-6-1-sol-medium": {"name": "GPT-6.1 Sol (Medium)", "evaluations": {
        "artificial_analysis_intelligence_index": 47.8}, "pricing": {}},
}
USAGE = {"anthropic": {"windows": [{"label": "Current session", "used_percent": 68.0},
                                   {"label": "Current week", "used_percent": 13.0}]},
         "openai-codex": {"unavailable_reason": "x"}}


class RouterTest(unittest.TestCase):
    def test_aa_slug(self):
        self.assertEqual(router.aa_slug("gpt-6.1-sol", "medium"), "gpt-6-1-sol-medium")
        self.assertEqual(router.aa_slug("anthropic/claude-opus-5.5", "max"), "claude-opus-5-5")
        self.assertEqual(router.aa_slug("gpt-6-sol-900k", "xhigh"), "gpt-6-sol-xhigh")
        self.assertEqual(router.aa_slug("claude-haiku-5-5", "weird"), "claude-haiku-5-5-medium")

    def test_options_lines(self):
        cands = [{"provider": "anthropic", "model": "claude-opus-5-5"}, {"provider": "openai-codex", "model": "gpt-6.1-sol"},
                 {"provider": "copilot", "model": "unknown-x"}]
        o = router.options(cands, AA, USAGE, "medium")
        self.assertEqual(list(o), ["anthropic/claude-opus-5-5", "openai-codex/gpt-6.1-sol", "copilot/unknown-x"])
        self.assertIn("종합 51.2, 엔지니어링 53.7 | $4/$20/Mtok", o["anthropic/claude-opus-5-5"])
        self.assertNotIn("코딩", o["anthropic/claude-opus-5-5"])  # null scores are omitted
        self.assertIn("Current session 32% 남음, Current week 87% 남음", o["anthropic/claude-opus-5-5"])
        self.assertIn("잔량 정보 없음", o["openai-codex/gpt-6.1-sol"])
        self.assertTrue(o["copilot/unknown-x"].startswith("벤치마크 없음"))

    def test_extra_scores_merge(self):
        extra = {"claude-opus-5-5-medium": {"Terminal-Bench 4.0": "53%", "NewEval": "7"},
                 "only-site-medium": {"SciCode": "50%"}}
        cands = [{"provider": "anthropic", "model": "claude-opus-5-5"}, {"provider": "x", "model": "only-site"}]
        o = router.options(cands, AA, USAGE, "medium", extra)
        self.assertIn("엔지니어링 53.7, TB4(에이전트코딩) 53%, NewEval 7 | $4/$20/Mtok", o["anthropic/claude-opus-5-5"])
        self.assertTrue(o["x/only-site"].startswith("AA[site] SciCode(코딩) 50%"))
        self.assertEqual(router.options(cands[:1], AA, USAGE, "medium"),
                         {"anthropic/claude-opus-5-5": router.options(cands[:1], AA, USAGE, "medium", {})["anthropic/claude-opus-5-5"]})

    def test_validate(self):
        avail = {"a": ["m1"], "b": ["m2"]}
        self.assertEqual(router.validate([{"provider": "a", "model": "m1"}], avail), [])
        self.assertEqual(len(router.validate([{"provider": "x", "model": "m"}, {"provider": "a", "model": "zz"}], avail)), 2)
        self.assertEqual(router.validate([], avail), ["candidates is empty"])

    def test_load_drops_legacy_tiers(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sub" / "candidates.json"
            self.assertEqual(router.load(p), [])
            router.save(p, [{"provider": "a", "model": "m", "tier": 2, "tasks": ["coding"]}])
            self.assertEqual(router.load(p), [{"provider": "a", "model": "m"}])

    def test_render_widget(self):
        html = router.render_widget("<script>const D = __DATA__;</script>", {"p": ["</script><b>"]}, [], "msg",
                                    {"effort": "medium"})
        self.assertNotIn("__DATA__", html)
        self.assertEqual(html.count("</script>"), 1)  # model id cannot close the script tag
        data = json.loads(html[len("<script>const D = "):-len(";</script>")].replace("<\\/", "</"))
        self.assertEqual(data["facts"], {"effort": "medium"})

    def test_parse_child(self):
        self.assertEqual(router.parse_child("NEEDS_INPUT: which branch?"),
                         {"status": "needs_input", "question": "which branch?"})
        self.assertEqual(router.parse_child(" done "), {"status": "done", "result": "done"})


if __name__ == "__main__":
    unittest.main()
