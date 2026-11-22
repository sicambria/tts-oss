---
name: todo
description: Open-work sweep + triage that chains into agent-protocol. Enumerates every backlog surface (active plans, open learning-loop findings, TODO/FIXME grep, live worktrees), triages each item do-now / skip / route-to-config with a reason, then hands the do-now set to the agent-protocol skill to drain. The disciplined answer to "what's left?" / "todo?".
triggers:
  - "/todo"
  - "todo?"
  - "what's left to do"
  - "sweep the backlog"
  - "what open work is there"
---

# todo

A named, repeatable sweep that answers *"what's left?"* honestly — by enumerating **every**
backlog surface in the repo, triaging each item, and then chaining the actionable set into the
[[agent-protocol]] skill to actually drain it. Genericized from changemappers'
`todo`-protocol; all paths resolve through `.harness/config.json`, never a hardcoded layout.

Exists because "what should I do next?" answered from memory silently drops work: a stale plan
stub, an open incident with no follow-up, a `TODO(after-launch)` buried in code, a half-merged
worktree. The sweep makes the backlog **complete and inspectable** before any work starts.

## When to invoke

- The user asks "todo?", "what's left?", "what's the open work?", or wants the backlog swept.
- At the top of a work session, to build a grounded picture before committing to a task.
- Before an `agent-protocol` wave, to produce the triaged item list it consumes.

Do **not** invoke for a single named task the user already scoped — just do that task.

## Grounding (read once)

Read `AGENTS.md` and `.harness/config.json`. Resolve from config, do not hardcode:
- `plan.dirs.active` / `plan.dirs.worktrees` / `plan.dirs.done` — plan lifecycle folders.
- `plan.claimsFile` — the worktree claims ledger.
- `docs.learningLoop.errorsDir` / `auditsDir` — where incidents/findings live.
- `defaultBranch` and the `verify` contract — the base every follow-up branches from.

## The sweep (enumerate every surface)

1. **Active plans** — every file in `plan.dirs.active` (and `plan.dirs.worktrees`) not yet moved
   to `plan.dirs.done`. A plan present here is unfinished by definition.
2. **Open learning-loop findings** — notes in `errorsDir` / `auditsDir` whose `Status` is
   `active` or `monitoring` (per `docs.learningLoop.allowedStatuses`), and any note whose
   `Automation Follow-Up` / `Guardrail Updates` section names undone work. Use
   `kaizen incident|audit` to file anything discovered mid-sweep that has no note yet.
3. **In-code markers** — `grep -rn` for `TODO`/`FIXME`/`XXX`/`HACK` across source (exclude
   `node_modules`, generated files, and this sweep's own docs). Group by file; note any dated or
   milestone-gated markers (`TODO(after-x)`).
4. **Live / abandoned worktrees** — `git worktree list --porcelain`. A worktree with commits not
   on `defaultBranch` is either in-flight (off-limits) or stranded (needs integrating or pruning).
5. **Doctor + verify drift** — run `kaizen doctor` and the `verify` contract; any WARN/FAIL is
   open work (unwired hook, unfilled verify step, disabled scanner, stale INDEX).

## Triage (every item gets a disposition — nothing silent)

Classify each swept item exactly as `agent-protocol` phase 1 does, so the output feeds it directly:
- **Do-now** — unblocked, positive cost-benefit, fits a disjoint domain.
- **Skip** — gated (product/data/infra), low cost-benefit, or infeasible. **Record the reason and
  a rough score** on the surface it came from — skips are documented, never dropped.
- **Route-to-config** — scanner/linter noise goes to the relevant exclusion/suppression config
  with a scoped rationale, not to a task. If a mechanism can't be validated, log the deferral
  under `.harness/archive/decisions/`.

## Chain into agent-protocol

Present the triaged backlog (do-now / skip / route, each with its reason). Then:
- If **multiple do-now items span disjoint domains** and the user opts into multi-agent work,
  hand the do-now set to the [[agent-protocol]] skill — its cluster→spawn→serialize-integrate
  loop drains them. Do not re-derive the triage; agent-protocol phase 1 consumes this one.
- If **one or two items** remain, run them inline through the `planmax` loop (plan→score→advisor→
  implement) rather than spinning up a fleet.
- If **everything is skip/gated**, say so plainly and stop — an empty do-now set is a valid,
  honest answer, not a prompt to invent work.

## Related

- [[agent-protocol]] — the multi-agent drain this sweep feeds.
- `planmax` skill — the plan→score→advisor→implement loop for the inline (1–2 item) path.
- `kaizen incident|audit` — file a learning-loop note for work discovered mid-sweep.
- `.harness/config.json` — `plan`, `docs.learningLoop`, `defaultBranch`, `verify`.
