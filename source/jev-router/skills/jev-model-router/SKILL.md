---
name: jev-model-router
description: "Use when choosing a model per task with Jev. Route and delegate."
version: 0.3.2
author: Gary-Y-Lee
license: MIT
---

# Jev model router

TypeSafe Jev picks the model for each task from the models the user allowed. Each option carries Artificial
Analysis (AA) benchmark scores and live subscription quota. The task then runs on that model as a subagent
(`jev_delegate`) linked to the current session. The current session keeps the conversation and asks the user
any questions. Reasoning effort is not chosen per task: children inherit the parent's level.

## Setup (once per Hermes install/profile, or when the user wants to change models)

0. **AA key check:** call `jev_router_models action=status`. If `aa_key_set` is false, tell the user `help` in one
   or two lines: get a free key at artificialanalysis.ai and add `AA_API_KEY=<key>` to `env_path`. Offer to open
   that file in their editor (Windows: `powershell.exe -NoProfile -Command "Start-Process notepad.exe -ArgumentList
   '\"<env_path>\"'"`). Never read, print, or accept the key in chat. After they save it, run `status` again; only
   `aa_key_set` and `aa_data` are checked. The user may skip: setup continues, and Jev then gets quota facts only.
   If the key is set but `aa_data` is false, report `help` (key error or network).
1. `jev_router_models action=show`. If allowed models already exist, skip to Routing unless the user asked to change them.
2. **Desktop app (default):** call `jev_router_models action=widget`. Put the returned `show` line
   (`::preview{file="..."}`) alone on its own line in your reply, and add one sentence asking the user to check the
   models they allow and press 저장. Each model shows its AA scores and each provider its remaining quota, for
   reference only. The user only checks; there are no tiers.
3. When a hidden user turn arrives that starts with `jev-router save `, parse the JSON after it and call
   `jev_router_models action=save` with its `candidates`. Then answer by updating the widget: call `action=widget`
   with `message` set to the result (for example "저장됨: 5개" or the error details) and show the new `::preview`
   line. Keep prose to one line.
4. **Fallback (no widget surface: messaging, CLI):** call `action=available`, then let the USER check models with
   `clarify` multi_select. Ask one question per provider, with at most 4 models per question and 5 questions per
   call. Then call `action=save`. Never pick models silently.

The list lives at `$HERMES_HOME/jev-router/candidates.json`, one per profile. AA scores need `AA_API_KEY` in `.env`
(cached for 24h). Quota comes from `hermes usage --json` (cached for 5 minutes).

## Extra per-evaluation scores (refresh ONLY when the user asks)

The free AA API has no coding or agentic index for most models. The user keeps per-evaluation scores
(Terminal-Bench, SciCode, GDPval, ...) in `$HERMES_HOME/jev-router/aa-extra.json`, and `options` appends them to
each model line. This file is personal, non-commercial data and is never collected automatically. Refresh it only
when the user asks, for example because models changed or new scores are needed:
1. Make sure Aside works (`aside --version`). Use `aside repl` (no Aside model needed); `aside exec` is slow on
   these chart-heavy pages.
2. Open AA comparison pages for pairs of the allowed models at the current effort:
   `https://artificialanalysis.ai/models/comparisons/<slugA>-vs-<slugB>`, where slugs come from `aa_slug`, e.g.
   `gpt-6-1-sol-medium`. Read `table tr` cells. Map columns by the header model names, not by URL order: the site
   reorders them.
3. Write `{"source", "fetched", "effort", "scores": {slug: {"Terminal-Bench 4.0": "53%", ...}}}` with the
   displayed strings. Cross-check one model that appears on two pages. Close the AA tabs you opened.
4. Tell the user the fetch date and any values marked "Under review".

## Routing a task

1. Answer directly, without routing, for trivial chat or quick lookups.
2. If the user named a model, call `jev_delegate` with `choice="<provider>/<model>"` and `user_override=true`. It must
   be an allowed model.
3. Call `jev_router_models action=options`. Then call the Jev MCP `choice` tool (on the `jev` server; if it is
   deferred, use `tool_search` for "jev") with `question` and `options` exactly as returned, and `context` set to a
   short task summary (goal, size, stakes, audience).
4. Call `jev_delegate` with `choice` set to Jev's `choice`, `confidence` set to Jev's confidence, `goal` set to the
   full instruction, and `context` set to everything the child needs (paths, constraints, earlier decisions). The
   child sees nothing else.
5. Report which model ran, Jev's confidence and runner-up, and the facts that drove the pick.

## needs_input loop (questions in the middle of a task)

Children cannot ask the user. When `jev_delegate` returns `status=needs_input`:
1. Ask the user the `question` with `clarify`.
2. Call `jev_delegate` again with the same `choice`, and add to `context` what the child already did plus
   `User answer: ...`.

## Pitfalls

- `ran_on` is the model that actually ran. If it differs from `route`, report it.
- `options.notes` saying AA is unavailable means only quota facts were sent. Tell the user that the pick is weaker.
- AA scores are for the effort shown in `options.effort`. If the session runs at another effort, scores shift.
- Subagents get a subset of tools and no memory. Put required paths and rules in `context`.
- If Jev tools are missing, say so and ask the user for a model. Do not invent probabilities.
