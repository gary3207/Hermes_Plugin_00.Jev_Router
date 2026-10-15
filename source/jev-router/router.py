"""Deterministic model choice from Jev labels and the user's saved candidates (stdlib only)."""
import json
from pathlib import Path

TASK_TYPES = ("coding", "research", "writing", "data", "simple_qa")
NEEDS_INPUT = "NEEDS_INPUT:"


def load(path: Path) -> list:
    if not path.is_file():
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("candidates", [])


def save(path: Path, candidates: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"candidates": candidates}, ensure_ascii=False, indent=2), encoding="utf-8")


def validate(candidates: list, available: dict) -> list:
    """Errors for candidates not usable in THIS environment; available = {provider_slug: [model ids]}."""
    errors = []
    if not candidates:
        errors.append("candidates is empty")
    for i, c in enumerate(candidates):
        p, m, t = c.get("provider"), c.get("model"), c.get("tier")
        if p not in available:
            errors.append(f"#{i} provider '{p}' is not authenticated here; available: {sorted(available)}")
        elif m not in available[p]:
            errors.append(f"#{i} model '{m}' not offered by '{p}'")
        if t not in (1, 2, 3):
            errors.append(f"#{i} tier must be 1, 2 or 3")
        bad = [x for x in c.get("tasks") or [] if x not in TASK_TYPES]
        if bad:
            errors.append(f"#{i} unknown tasks {bad}; allowed {list(TASK_TYPES)}")
    return errors


def required_tier(difficulty: int, quality_critical: bool, confidence: float) -> int:
    tier = 1 if difficulty <= 2 else 2 if difficulty == 3 else 3
    if quality_critical:
        tier = 3
    if confidence < 0.6:  # Jev unsure of its labels -> one step safer
        tier = min(3, tier + 1)
    return tier


def route(candidates: list, task_type: str, difficulty: int, quality_critical: bool, confidence: float):
    """(candidate, reason). Exact tier, else nearest higher, else nearest lower; task match beats generic."""
    if not candidates:
        raise ValueError("no candidate models saved; run jev_router_models action=save first")
    need = required_tier(difficulty, quality_critical, confidence)
    tiers = sorted({c["tier"] for c in candidates}, key=lambda t: (t < need, abs(t - need)))
    pool = [c for c in candidates if c["tier"] == tiers[0]]
    pick = (next((c for c in pool if task_type in (c.get("tasks") or [])), None)
            or next((c for c in pool if not c.get("tasks")), None) or pool[0])
    reason = (f"task={task_type} difficulty={difficulty} quality_critical={quality_critical} "
              f"confidence={confidence:.2f} -> need tier {need}, chose tier {pick['tier']}")
    return pick, reason


def parse_child(summary: str) -> dict:
    """Child protocol: a final answer starting with NEEDS_INPUT: is a question for the user."""
    text = (summary or "").strip()
    if text.startswith(NEEDS_INPUT):
        return {"status": "needs_input", "question": text[len(NEEDS_INPUT):].strip()}
    return {"status": "done", "result": text}
