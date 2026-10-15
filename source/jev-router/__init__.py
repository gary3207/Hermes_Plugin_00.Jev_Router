"""jev-router: Jev picks the model per task from the user's allowed candidates, using AA benchmarks and live
subscription quota; the task then runs as a linked subagent on that model."""
import json
import shutil
import subprocess
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import router

CHILD_PROTOCOL = (
    "\n\n[jev-router protocol] If you cannot finish without a decision only the user can make, do not guess: "
    f"stop and make your whole final answer one line '{router.NEEDS_INPUT} <one concise question>'."
)
AA_URL = "https://artificialanalysis.ai/api/v2/language/models/free?page={}"
AA_TTL, USAGE_TTL = 24 * 3600, 300  # AA free tier: 1000 req/day, asks callers to cache


def _home() -> Path:
    from hermes_constants import get_hermes_home  # profile-safe
    return get_hermes_home() / "jev-router"


def _config_path() -> Path:
    return _home() / "candidates.json"


def _cached(name: str, ttl: int, fetch):
    """JSON cache under $HERMES_HOME/jev-router; a failed refresh falls back to the stale copy."""
    path = _home() / name
    if path.is_file() and time.time() - path.stat().st_mtime < ttl:
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        data = fetch()
    except Exception:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def _fetch_aa() -> list:
    from hermes_cli.config import get_env_value  # profile-scoped environ, then $HERMES_HOME/.env
    api_key = get_env_value("AA_API_KEY")
    if not api_key:
        raise RuntimeError("AA_API_KEY not set")
    rows, page = [], 1
    while True:
        req = urllib.request.Request(AA_URL.format(page), headers={"x-api-key": api_key})
        with urllib.request.urlopen(req, timeout=30) as r:
            body = json.load(r)
        rows += body["data"]
        if not body.get("pagination", {}).get("has_more"):
            return rows
        page += 1


def _aa() -> dict:
    return {r["slug"]: r for r in _cached("aa-cache.json", AA_TTL, _fetch_aa) or []}


def _usage_one(provider: str):
    exe = shutil.which("hermes")
    if not exe:
        return None
    p = subprocess.run([exe, "usage", "--provider", provider, "--json"], capture_output=True, text=True,
                       timeout=60, encoding="utf-8", errors="replace")
    return json.loads(p.stdout) if p.returncode == 0 else None


def _usage(providers) -> dict:
    """{provider: `hermes usage --json`} via the public CLI, cached 5 minutes as a whole."""
    providers = sorted(set(providers))

    def fetch():
        with ThreadPoolExecutor(max_workers=max(1, len(providers))) as ex:
            return dict(zip(providers, ex.map(_usage_one, providers)))
    cached = _cached("usage-cache.json", USAGE_TTL, fetch) or {}
    if not set(providers) <= set(cached):  # candidate set changed since the cache was written
        (_home() / "usage-cache.json").unlink(missing_ok=True)
        cached = _cached("usage-cache.json", USAGE_TTL, fetch) or {}
    return cached


def _effort() -> str:
    # Children inherit the parent's reasoning level; the configured default is the best guess a tool can see.
    try:
        from hermes_cli.config import load_config_readonly
        cfg = load_config_readonly()
        value = (cfg.get("agent") or {}).get("reasoning_effort") or cfg.get("reasoning_effort") or "medium"
        return value if isinstance(value, str) else "medium"
    except Exception:
        return "medium"


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
        cands = [{"provider": c.get("provider"), "model": c.get("model")} for c in args.get("candidates") or []]
        errors = router.validate(cands, _available())
        if errors:
            return _ok(error="not saved", details=errors)
        router.save(_config_path(), cands)
        return _ok(saved=len(cands), path=str(_config_path()))
    if action == "options":
        cands = router.load(_config_path())
        if not cands:
            return _ok(error="no candidate models saved; run setup (action=widget) first")
        effort = _effort()
        aa, usage = _aa(), _usage(c["provider"] for c in cands)
        return _ok(question=router.QUESTION, options=router.options(cands, aa, usage, effort), effort=effort,
                   notes=[] if aa else ["AA benchmark unavailable (AA_API_KEY missing or fetch failed)"])
    if action == "widget":
        avail, saved, effort = _available(), router.load(_config_path()), _effort()
        aa, usage = _aa(), _usage(avail)
        facts = {"effort": effort,
                 "bench": {router.key({"provider": p, "model": m}): router.bench_text(aa.get(router.aa_slug(m, effort)))
                           for p, ms in avail.items() for m in ms},
                 "quota": {p: router.quota_text(usage.get(p)) for p in avail}}
        out = _home() / "setup.html"
        tpl = (Path(__file__).parent / "widget.html").read_text(encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(router.render_widget(tpl, avail, saved, args.get("message", ""), facts), encoding="utf-8")
        return _ok(path=str(out), show=f'::preview{{file="{out.as_posix()}"}}')
    return _ok(error="action must be options, widget, available, show or save")


def _make_delegate(ctx):
    def _delegate(args: dict, **_) -> str:
        cands = {router.key(c): c for c in router.load(_config_path())}
        pick = cands.get(args.get("choice", ""))
        if not pick:  # trust boundary: only models the user allowed
            return _ok(error=f"choice '{args.get('choice')}' is not a saved candidate", allowed=sorted(cands))
        route = {"provider": pick["provider"], "model": pick["model"], "jev_confidence": args.get("confidence"),
                 "by": "user override" if args.get("user_override") else "jev choice"}
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
    "description": ("jev-router candidate models. action=options returns {question, options} to pass unchanged to "
                    "the Jev MCP `choice` tool (options carry AA benchmark scores and live subscription quota per "
                    "allowed model). action=widget writes a checkbox picker (desktop) and returns a ::preview line to "
                    "put alone on its own line; its Save button sends 'jev-router save {json}'. action=available lists "
                    "models authenticated in THIS Hermes; action=show prints the allowed list; action=save stores the "
                    "models the USER checked (validated against available)."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["options", "widget", "available", "show", "save"]},
        "message": {"type": "string", "description": "widget only: status text shown at the top (e.g. save result)."},
        "candidates": {"type": "array", "items": {"type": "object", "properties": {
            "provider": {"type": "string"}, "model": {"type": "string"}}, "required": ["provider", "model"]}}},
        "required": ["action"]},
}

DELEGATE_SCHEMA = {
    "name": "jev_delegate",
    "description": ("Run one task as a subagent on the model Jev chose (`choice` = the option id 'provider/model' "
                    "returned by Jev for jev_router_models action=options). The child is linked to this session. "
                    "Returns status=done with result, or status=needs_input with a question: ask the user via "
                    "clarify, then call again with the answer added to context."),
    "parameters": {"type": "object", "properties": {
        "goal": {"type": "string"}, "context": {"type": "string"},
        "choice": {"type": "string", "description": "Allowed candidate id 'provider/model'."},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Jev's confidence for choice."},
        "user_override": {"type": "boolean", "description": "true when the user named the model instead of Jev."}},
        "required": ["goal", "choice"]},
}


def register(ctx):
    root = Path(__file__).parent
    ctx.register_tool(name="jev_router_models", toolset="jev_router", schema=MODELS_SCHEMA, handler=_models)
    ctx.register_tool(name="jev_delegate", toolset="jev_router", schema=DELEGATE_SCHEMA, handler=_make_delegate(ctx))
    ctx.register_skill("jev-model-router", root / "skills" / "jev-model-router" / "SKILL.md",
                       description="Use when choosing a model per task with Jev. Route and delegate.")
