"""jev-router: per-task model choice (Jev labels -> user's candidate table) and delegation on that model."""
import json
from pathlib import Path

from . import router

CHILD_PROTOCOL = (
    "\n\n[jev-router protocol] If you cannot finish without a decision only the user can make, do not guess: "
    f"stop and make your whole final answer one line '{router.NEEDS_INPUT} <one concise question>'."
)


def _config_path() -> Path:
    from hermes_constants import get_hermes_home  # profile-safe
    return get_hermes_home() / "jev-router" / "candidates.json"


def _available() -> dict:
    from hermes_cli.model_switch_providers import list_authenticated_providers
    return {p["slug"]: list(p.get("models") or []) for p in list_authenticated_providers(non_blocking_catalogs=True)}


def _ok(**data) -> str:
    return json.dumps(data, ensure_ascii=False)


def _models(args: dict, **_) -> str:
    action = args.get("action")
    if action == "available":
        return _ok(available=_available())
    if action == "show":
        return _ok(path=str(_config_path()), candidates=router.load(_config_path()))
    if action == "save":
        cands = args.get("candidates") or []
        errors = router.validate(cands, _available())
        if errors:
            return _ok(error="not saved", details=errors)
        router.save(_config_path(), cands)
        return _ok(saved=len(cands), path=str(_config_path()))
    return _ok(error="action must be available, show or save")


def _make_delegate(ctx):
    def _delegate(args: dict, **_) -> str:
        cands = router.load(_config_path())
        alias = args.get("override_model")
        try:
            if alias:  # user-forced model must still be one they saved
                pick = next(c for c in cands if c["model"] == alias)
                reason = "user override"
            else:
                pick, reason = router.route(
                    cands, args.get("task_type", ""), int(args.get("difficulty", 3)),
                    bool(args.get("quality_critical", False)), float(args.get("confidence", 1.0)))
        except StopIteration:
            return _ok(error=f"override_model '{alias}' is not a saved candidate")
        except ValueError as exc:
            return _ok(error=str(exc))
        route = {"provider": pick["provider"], "model": pick["model"], "reason": reason}
        if args.get("dry_run"):
            return _ok(route=route)
        svc = ctx.subagent_lifecycle
        try:
            handle = svc.launch({"goal": args["goal"], "context": (args.get("context") or "") + CHILD_PROTOCOL,
                                 "provider": pick["provider"], "model": pick["model"]})
        except (ValueError, KeyError) as exc:  # SubagentLifecycleError is a ValueError
            return _ok(error=f"launch failed: {exc}", route=route)
        svc.wait(handle)
        res = svc.result(handle)
        out = {"route": route, "ran_on": {"provider": res.handle.provider, "model": res.handle.model},
               "state": res.terminal_state.value}
        if res.error_message:
            out["error"] = res.error_message
        out.update(router.parse_child(res.summary or ""))
        return _ok(**out)
    return _delegate


MODELS_SCHEMA = {
    "name": "jev_router_models",
    "description": ("Manage the user's candidate models for jev-router. action=available lists providers/models "
                    "authenticated in THIS Hermes; action=show prints the saved table; action=save stores "
                    "candidates the USER chose (validated against available). tier: 1 light/fast, 2 standard, "
                    "3 strongest. tasks (optional) prefers a model for: " + ", ".join(router.TASK_TYPES) + "."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["available", "show", "save"]},
        "candidates": {"type": "array", "items": {"type": "object", "properties": {
            "provider": {"type": "string"}, "model": {"type": "string"},
            "tier": {"type": "integer", "enum": [1, 2, 3]},
            "tasks": {"type": "array", "items": {"type": "string", "enum": list(router.TASK_TYPES)}}},
            "required": ["provider", "model", "tier"]}}},
        "required": ["action"]},
}

DELEGATE_SCHEMA = {
    "name": "jev_delegate",
    "description": ("Run one task as a subagent on the model jev-router picks from Jev labels (task_type, "
                    "difficulty, quality_critical, confidence) and the user's candidate table. The child is linked "
                    "to this session. Returns status=done with result, or status=needs_input with a question: ask "
                    "the user via clarify, then call again with the answer added to context. dry_run=true only "
                    "returns the route."),
    "parameters": {"type": "object", "properties": {
        "goal": {"type": "string"}, "context": {"type": "string"},
        "task_type": {"type": "string", "enum": list(router.TASK_TYPES)},
        "difficulty": {"type": "integer", "minimum": 1, "maximum": 5},
        "quality_critical": {"type": "boolean"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1,
                       "description": "Lowest Jev probability among the labels used."},
        "override_model": {"type": "string", "description": "Saved candidate model the user explicitly asked for."},
        "dry_run": {"type": "boolean"}},
        "required": ["goal", "task_type", "difficulty", "quality_critical", "confidence"]},
}


def register(ctx):
    root = Path(__file__).parent
    ctx.register_tool(name="jev_router_models", toolset="jev_router", schema=MODELS_SCHEMA, handler=_models)
    ctx.register_tool(name="jev_delegate", toolset="jev_router", schema=DELEGATE_SCHEMA, handler=_make_delegate(ctx))
    ctx.register_skill("jev-model-router", root / "skills" / "jev-model-router" / "SKILL.md",
                       description="Use when choosing a model per task with Jev. Route and delegate.")
