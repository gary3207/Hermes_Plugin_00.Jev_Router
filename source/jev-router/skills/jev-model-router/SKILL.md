---
name: jev-model-router
description: "Use when choosing a model per task with Jev. Route and delegate."
version: 0.1.0
author: Gary-Y-Lee
license: MIT
---

# Jev model router

Pick a model for one task with TypeSafe Jev labels and the user's candidate table, then run the task as a
subagent on that model with `jev_delegate`. The child is linked to the current session. The current session
keeps the conversation and asks the user any questions.

## Setup (once per Hermes install/profile, or when the user wants to change models)

1. `jev_router_models action=show`. If candidates already exist, skip to Routing unless the user asked to change them.
2. `jev_router_models action=available`. Lists only providers and models authenticated in THIS Hermes, so it
   differs per machine and subscription.
3. The USER chooses. Ask with `clarify` (multi_select) which models to use, at most 4 per question. Then propose a
   tier for each one (1 light/fast, 2 standard, 3 strongest) and optional preferred `tasks`, and let the user
   confirm or edit. Never pick candidates silently.
4. `jev_router_models action=save candidates=[...]`. Save validates against `available`. Fix any reported errors
   with the user.

The table lives at `$HERMES_HOME/jev-router/candidates.json`, one per profile. It is not in Git.

## Routing a task

1. Skip routing and answer directly when the request is trivial chat or a quick lookup. Also skip it when the user
   named a model: pass `override_model` (it must be a saved candidate).
2. Label the request with Jev (MCP tools `choice`, `score`, `noul` on the `jev` server; if they are deferred, use
   `tool_search` for "jev"). Pass a short summary as `context`:
   - `choice`, question "Which kind of task is this?", options `coding`, `research`, `writing`, `data`, `simple_qa`.
   - `score`, question "How difficult is this task for an AI agent?", levels
     `["trivial","easy","medium","hard","expert"]`. difficulty = round(score) + 1.
   - `noul`, question "Would mistakes be costly or does the output go to external stakeholders?".
     quality_critical = noul >= 0.5.
   - confidence = the lower of the choice and score confidences.
3. If task_type is `simple_qa` and difficulty <= 2, answer directly.
4. Otherwise call `jev_delegate` with `goal` (the full instruction), `context` (everything the child needs: paths,
   constraints, earlier decisions; the child sees nothing else), and the four labels.
5. Tell the user which model ran and why (`route.reason`).

## needs_input loop (questions in the middle of a task)

Children cannot ask the user. When `jev_delegate` returns `status=needs_input`:
1. Ask the user the `question` with `clarify`.
2. Call `jev_delegate` again with the same labels, and add to `context` what the child already did (from its
   output) plus `User answer: ...`.

## Pitfalls

- `ran_on` is the model that actually ran. If it differs from `route`, report it.
- Subagents get a subset of tools and no memory. Put required paths and rules in `context`.
- If Jev tools are missing, say so and ask the user for the labels or a model. Do not invent probabilities.
