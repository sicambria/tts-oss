---
name: planmax
description: Plan-score-iterate-implement workflow. Reuses or drafts a plan, scores it 0-100 against a grounding/concreteness rubric, iterates until it clears 90, gets an advisor sign-off, then implements and updates docs.
triggers:
  - "/planmax"
  - "planmax"
  - "plan it out and score it"
  - "iterate the plan until it's good enough"
---

# planmax

Turns "write a plan" into a closed loop: draft/reuse → score → revise → advisor gate → implement → docs. Exists because a plan that was never scored or challenged tends to survive review by accident, not by merit.

## Behavior contract

1. **Locate or draft the plan.**
   - If `.harness/config.json` exists, read `plan.dirs.active` for the plans folder (fall back to `docs/plans` if unset) and `plan.dirs.done` for where finished plans move. Otherwise default to a `plans/` folder at repo root.
   - Search that folder for an existing plan matching the task. If found, use it as the starting draft — don't write a new one from scratch.
   - If none exists, draft one. Match whatever plan template the repo uses (`.harness/plans/` conventions, a `plan.planTypes` list in config, etc.) if present; otherwise use: Summary, Steps, Risks/Reversibility, Test plan, and a `## Standards & Guardrails Evidence` section.

2. **Score the plan 0-100** against this rubric (weights sum to 100; adjust axis names but not the total if the repo's config implies different dimensions):
   - **Evidence grounding & dimension coverage (30 pts)** — if `.harness/config.json` defines `plan.dimensions`, every dimension has a citation (`path:line`) that resolves against the working tree, or an explicit `N/A — reason`. No dimensions ⇒ full credit if the plan still cites concrete evidence for its key claims.
   - **Required structure present (15 pts)** — required sections/metadata exist, no placeholders (`TBD`, `FIXME`, `XXX`, `<stub>`).
   - **Concreteness & verifiability (20 pts)** — every step is actionable and ordered, and maps to a way to verify it's done (a test, a command from `verify` in config, a manual check called out explicitly).
   - **Risk & reversibility (15 pts)** — blast radius named, rollback/backout path stated, destructive or hard-to-reverse actions flagged for confirmation.
   - **Test / shift-left coverage (10 pts)** — new or changed behavior has a named test (existing or to-be-written), not just "will test manually."
   - **Scope discipline (10 pts)** — plan matches what was actually asked; no speculative abstractions, unrequested features, or gold-plating.

3. **Iterate.** If score ≤ 90, revise the plan to address the lowest-scoring axes first, then rescore. Repeat. Don't inflate a score to clear the bar — a 91 that ignores a real gap is worse than an honest 78 that names it.

3b. **KEEP_BASE norm.** If the evidence does not argue for any change, leave everything as it
    is and return `KEEP_BASE` — a real answer, not a failure (adaptation the evidence does not
    support costs context and buys nothing; src: `harness2/core/prompts.py`). KEEP_BASE
    terminates *iteration*, never *obligation*: it requires (a) recorded behavioral evidence
    examined, (b) a rationale naming what was tried and why no candidate earned adoption —
    bare "KEEP_BASE, no reason" is a failure — and (c) a counted `kept_base` entry in the
    machine-readable score output below. This is distinct from SKIP (infeasible) and
    infra-stall: KEEP_BASE means feasible work, examined evidence, correctly no change.

Machine-readable score output (every score/rescore/KEEP_BASE return emits this shape):

```json
{ "total": 94, "axes": { "grounding": 28, "structure": 15, "concreteness": 20, "risk": 15, "tests": 8, "scope": 8 }, "kept_base": 0, "rationale": "<what was tried; required when kept_base=1>" }
```

4. **Advisor gate.** Once self-score > 90, call the advisor with the plan and its score breakdown. The advisor is a check on the loop, not a formality:
   - If the advisor surfaces a material gap in any rubric axis, treat it as a rescore — drop the score to reflect it and reopen the iterate loop (step 3).
   - Only proceed once the plan holds > 90 *and* the advisor has no unresolved blocking objections.

5. **Implement.** Follow the repo's own operating contract while doing so (e.g. this repo's `AGENTS.md`: worktree-first off the default branch for substantive changes, never `--no-verify`, run the configured `verify` contract before calling it done).

6. **Update docs.** Whatever the plan's evidence/documentation dimensions call for — README, AGENTS.md/CLAUDE.md, CHANGELOG, or repo-specific docs. If the repo has a plan "done" directory (`plan.dirs.done`), move the finished plan there. If the work uncovered a real bug, follow the repo's incident/learning-loop process instead of silently fixing it.

## When to use

- Any non-trivial implementation task where you want a plan vetted before code gets written, not after.
- The user explicitly invokes `/planmax` or asks to "score and iterate the plan."

## When NOT to use

- Trivial, mechanical, one-line changes — the scoring ceremony costs more than it returns.
- The user wants a plan *reviewed once*, not iterated to a bar — just plan and ask, don't force the loop.
- Emergency/incident fixes where speed matters more than plan polish — stabilize first, retro after.

## Iron rules

- Never self-report a score without stating which axis lost which points — an opaque "94/100" is not a score, it's a claim.
- Never treat the advisor call as a rubber stamp — its objections can and should reopen the loop.
- Never implement before the plan is both > 90 and advisor-cleared.
- Evidence citations must resolve against the actual working tree — a plausible-looking `path:line` that doesn't exist is a hard failure of axis 1, not a rounding error.
- Don't invent process the repo doesn't have (e.g. a `.harness/plans` evidence heading) when none exists — degrade gracefully to the generic template in step 1.
