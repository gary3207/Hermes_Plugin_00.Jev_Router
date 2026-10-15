"""jev-router core (stdlib only): candidates, AA benchmark matching, quota text, Jev option lines, child protocol."""
import json
import re
from pathlib import Path

NEEDS_INPUT = "NEEDS_INPUT:"
QUESTION = ("Which model should run this task? Choose the cheapest model whose benchmark scores are enough for the "
            "task's difficulty and stakes; prefer stronger models for hard or high-stakes work; avoid models whose "
            "remaining quota is low.")
# AA slug suffix per Hermes reasoning effort; AA's bare slug is the max-effort run.
EFFORT_SUFFIX = {"none": "-non-reasoning", "minimal": "-low", "low": "-low", "medium": "-medium",
                 "high": "-high", "xhigh": "-xhigh", "max": ""}
AA_FIELDS = (("artificial_analysis_intelligence_index", "종합"), ("artificial_analysis_coding_index", "코딩"),
             ("artificial_analysis_agentic_index", "에이전트"), ("artificial_analysis_engineering_index", "엔지니어링"),
             ("artificial_analysis_strategy_and_ops_index", "전략"),
             ("artificial_analysis_finance_and_accounting_index", "금융"), ("artificial_analysis_legal_index", "법률"))


def key(c: dict) -> str:
    return f"{c['provider']}/{c['model']}"


def load(path: Path) -> list:
    if not path.is_file():
        return []
    # tier/tasks saved by 0.1-0.2 are dropped: Jev chooses the model now
    return [{"provider": c["provider"], "model": c["model"]}
            for c in json.loads(path.read_text(encoding="utf-8")).get("candidates", [])]


def save(path: Path, candidates: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")


def validate(candidates: list, available: dict) -> list:
    """Errors for candidates not usable in THIS environment; available = {provider_slug: [model ids]}."""
    if not candidates:
        return ["candidates is empty"]
    errors = []
    for i, c in enumerate(candidates):
        p, m = c.get("provider"), c.get("model")
        if p not in available:
            errors.append(f"#{i} provider '{p}' is not authenticated here; available: {sorted(available)}")
        elif m not in available[p]:
            errors.append(f"#{i} model '{m}' not offered by '{p}'")
    return errors


def aa_slug(model: str, effort: str) -> str:
    # shortcut: AA slug derived by rule (vendor prefix, dots, -900k variants); add an alias table if AA renames
    base = re.sub(r"-\d+k$", "", model.split("/")[-1].lower().replace(".", "-"))
    return base + EFFORT_SUFFIX.get(effort, "-medium")


def bench_text(row) -> str:
    if not row:
        return "벤치마크 없음"
    ev = row.get("evaluations") or {}
    parts = [f"{label} {ev[f]:g}" for f, label in AA_FIELDS if ev.get(f) is not None]
    pr = row.get("pricing") or {}
    price = f" | ${pr['price_1m_input_tokens']:g}/${pr['price_1m_output_tokens']:g}/Mtok" \
        if pr.get("price_1m_input_tokens") is not None and pr.get("price_1m_output_tokens") is not None else ""
    return f"AA[{row.get('name')}] " + ", ".join(parts) + price


def quota_text(usage) -> str:
    """usage = parsed `hermes usage --json` for the provider, or None."""
    if not usage or usage.get("unavailable_reason"):
        return "잔량 정보 없음"
    wins = [f"{w['label']} {100 - w['used_percent']:g}% 남음" for w in usage.get("windows", [])
            if w.get("used_percent") is not None]
    return "잔량 " + ", ".join(wins) if wins else "잔량 정보 없음"


def options(candidates: list, aa: dict, usage: dict, effort: str) -> dict:
    """Jev choice options {provider/model: one-line facts}; aa = {slug: AA row}, usage = {provider: json}."""
    return {key(c): f"{bench_text(aa.get(aa_slug(c['model'], effort)))} | {quota_text(usage.get(c['provider']))}"
            for c in candidates}


def parse_child(summary: str) -> dict:
    """Child protocol: a final answer starting with NEEDS_INPUT: is a question for the user."""
    text = (summary or "").strip()
    if text.startswith(NEEDS_INPUT):
        return {"status": "needs_input", "question": text[len(NEEDS_INPUT):].strip()}
    return {"status": "done", "result": text}


def render_widget(template: str, available: dict, saved: list, message: str = "", facts: dict = None) -> str:
    data = json.dumps({"available": available, "saved": saved, "message": message, "facts": facts or {}},
                      ensure_ascii=False)
    return template.replace("__DATA__", data.replace("</", "<\\/"))  # no </script> breakout from model ids
