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


AA_KEY_HELP = ("AA_API_KEY가 없어 벤치마크를 Jev에 보낼 수 없습니다. artificialanalysis.ai에 가입해 무료 API 키를 "
               "발급받고 {env}에 AA_API_KEY=<키> 한 줄을 추가하세요. 키는 채팅에 붙여넣지 마세요.")


def _aa_key():
    from hermes_cli.config import get_env_value  # profile-scoped environ, then $HERMES_HOME/.env
    return get_env_value("AA_API_KEY")


def _aa_status(aa: dict) -> dict:
    """Never returns the key itself."""
    from hermes_constants import get_hermes_home
    env = str(get_hermes_home() / ".env")
    key_set = bool(_aa_key())
    help_text = "" if key_set and aa else AA_KEY_HELP.format(env=env) if not key_set else \
        "AA_API_KEY는 있지만 벤치마크 조회에 실패했습니다(키 오류 또는 네트워크). 키를 확인하세요."
    return {"aa_key_set": key_set, "aa_data": bool(aa), "env_path": env, "help": help_text}


def _fetch_aa() -> list:
    api_key = _aa_key()
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


def _extra() -> dict:
    """Per-evaluation scores the user had collected from the AA site ({slug: {eval: score}}); absent = {}."""
    path = _home() / "aa-extra.json"
    return json.loads(path.read_text(encoding="utf-8")).get("scores", {}) if path.is_file() else {}


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
    if action == "status":
        return _ok(**_aa_status(_aa()))
    if action == "options":
        cands = router.load(_config_path())
        if not cands:
            return _ok(error="no candidate models saved; run setup (action=widget) first")
        effort = _effort()
        aa, usage = _aa(), _usage(c["provider"] for c in cands)
        return _ok(question=router.QUESTION, options=router.options(cands, aa, usage, effort, _extra()), effort=effort,
                   notes=[] if aa else [_aa_status(aa)["help"]])
    if action == "widget":
        avail, saved, effort = _available(), router.load(_config_path()), _effort()
        aa, usage, extra = _aa(), _usage(avail), _extra()
        facts = {"effort": effort, "aa_help": _aa_status(aa)["help"],
                 "bench": {router.key({"provider": p, "model": m}):
                           router.bench_text(aa.get(router.aa_slug(m, effort)), extra.get(router.aa_slug(m, effort)))
                           for p, ms in avail.items() for m in ms},
                 "quota": {p: router.quota_text(usage.get(p)) for p in avail}}
        out = _home() / "setup.html"
        tpl = (Path(__file__).parent / "widget.html").read_text(encoding="utf-8")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(router.render_widget(tpl, avail, saved, args.get("message", ""), facts), encoding="utf-8")
        return _ok(path=str(out), show=f'::preview{{file="{out.as_posix()}"}}')
    return _ok(error="action must be status, options, widget, available, show or save")


def _make_delegate(ctx):
    def _one(svc, cands, t):
        pick = cands.get(t.get("choice", ""))
        if not pick:  # trust boundary: only models the user allowed
            return None, _err(f"choice '{t.get('choice')}' is not a saved candidate", allowed=sorted(cands))
        route = {"provider": pick["provider"], "model": pick["model"], "jev_confidence": t.get("confidence"),
                 "by": "user override" if t.get("user_override") else "jev choice"}
        try:
            handle = svc.launch({"goal": t["goal"], "context": (t.get("context") or "") + CHILD_PROTOCOL,
                                 "provider": pick["provider"], "model": pick["model"]})
        except (ValueError, KeyError) as exc:  # SubagentLifecycleError is a ValueError
            return None, {"error": f"launch failed: {exc}", "route": route}
        return handle, {"route": route}

    def _delegate(args: dict, **_) -> str:
        cands = {router.key(c): c for c in router.load(_config_path())}
        tasks = args.get("tasks") or [args]
        svc = ctx.subagent_lifecycle
        launched = [_one(svc, cands, t) for t in tasks]  # launch all first so children run in parallel
        out = []
        for handle, entry in launched:
            if handle is not None:
                svc.wait(handle)
                res = svc.result(handle)
                entry.update(ran_on={"provider": res.handle.provider, "model": res.handle.model},
                             state=res.terminal_state.value)
                if res.error_message:
                    entry["error"] = res.error_message
                entry.update(router.parse_child(res.summary or ""))
            out.append(entry)
        return _ok(**out[0]) if "tasks" not in args else _ok(results=out)
    return _delegate


def _err(msg, **kw) -> dict:
    return {"error": msg, **kw}


ROUTE_NOTICE = (
    "jev-router: subagent models are chosen by Jev, so delegate_task is not used while allowed models are saved. "
    "Instead: 1) jev_router_models action=options. 2) Jev MCP (tool_search 'jev' if deferred): one task -> `choice` "
    "with question/options as returned and context=task summary; several tasks -> one `classify` call with "
    "items=one short summary per task and the same question/options. 3) ONE jev_delegate call with tasks=[{goal, "
    "context, choice, confidence}, ...] (runs in parallel; put any output format rules in context). If the user "
    "named a model, use it as choice with user_override=true."
)


def _route_guard(tool_name: str = "", args: dict = None, **_):
    """pre_tool_call: steer spawning delegate_task to Jev routing; fail open when routing is not set up."""
    if tool_name != "delegate_task" or (args or {}).get("action", "spawn") != "spawn":
        return None
    try:
        if not router.load(_config_path()):
            return None
    except Exception:
        return None
    return {"action": "block", "message": ROUTE_NOTICE}


MODELS_SCHEMA = {
    "name": "jev_router_models",
    "description": ("jev-router candidate models. action=status reports whether AA_API_KEY is set and AA data loads "
                    "(never the key) with a Korean help text. action=options returns {question, options} to pass unchanged to "
                    "the Jev MCP `choice` tool (options carry AA benchmark scores and live subscription quota per "
                    "allowed model). action=widget writes a checkbox picker (desktop) and returns a ::preview line to "
                    "put alone on its own line; its Save button sends 'jev-router save {json}'. action=available lists "
                    "models authenticated in THIS Hermes; action=show prints the allowed list; action=save stores the "
                    "models the USER checked (validated against available)."),
    "parameters": {"type": "object", "properties": {
        "action": {"type": "string", "enum": ["status", "options", "widget", "available", "show", "save"]},
        "message": {"type": "string", "description": "widget only: status text shown at the top (e.g. save result)."},
        "candidates": {"type": "array", "items": {"type": "object", "properties": {
            "provider": {"type": "string"}, "model": {"type": "string"}}, "required": ["provider", "model"]}}},
        "required": ["action"]},
}

_TASK_PROPS = {
    "goal": {"type": "string"}, "context": {"type": "string"},
    "choice": {"type": "string", "description": "Allowed candidate id 'provider/model'."},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1, "description": "Jev's confidence for choice."},
    "user_override": {"type": "boolean", "description": "true when the user named the model instead of Jev."}}

DELEGATE_SCHEMA = {
    "name": "jev_delegate",
    "description": ("Run tasks as subagents on the models Jev chose (`choice` = the option id 'provider/model' "
                    "returned by Jev for jev_router_models action=options). Children are linked to this session. "
                    "Pass `tasks` to run several in parallel (returns results[] in order), or a single goal/choice. "
                    "Each result has status=done with result, or status=needs_input with a question: ask the user "
                    "via clarify, then call again for that task with the answer added to context."),
    "parameters": {"type": "object", "properties": {
        **_TASK_PROPS,
        "tasks": {"type": "array", "minItems": 1, "items": {"type": "object", "properties": _TASK_PROPS,
                                                            "required": ["goal", "choice"]}}}},
}


def register(ctx):
    root = Path(__file__).parent
    ctx.register_tool(name="jev_router_models", toolset="jev_router", schema=MODELS_SCHEMA, handler=_models)
    ctx.register_tool(name="jev_delegate", toolset="jev_router", schema=DELEGATE_SCHEMA, handler=_make_delegate(ctx))
    ctx.register_hook("pre_tool_call", _route_guard)
    ctx.register_skill("jev-model-router", root / "skills" / "jev-model-router" / "SKILL.md",
                       description="Use when delegating subagents or choosing a model per task. Jev routes.")
