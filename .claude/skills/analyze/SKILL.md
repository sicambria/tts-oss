---
name: analyze
description: Cross-artifact consistency check (Spec Kit /analyze) — read the plan, the stated intent/spec, and the current code together and surface every contradiction, coverage gap, and scope drift BEFORE human approval. Produces a written report that the /next phase gate requires to advance into the approval phase. Non-destructive and read-only; it finds problems, it does not fix them.
context: fork
agent: Explore
background: false
triggers:
  - "/analyze"
  - "consistency check the plan"
  - "plan vs code drift"
  - "cross-artifact check"
---

# analyze

A read-only consistency pass that reconciles three artifacts before any human approves execution:

1. **Plan** — the plan file under `config.plan.dirs.worktrees` (the intended change).
2. **Intent / spec** — the task/issue/spec the plan claims to satisfy.
3. **Code** — the current tree the plan will touch.

It is the `/next` step between the Phase-1 gate and human approval. Approval on an *inconsistent*
plan is how the wrong thing ships fast; `/analyze` is the automated evidence the human approves
against, and the `/next` gate **will not advance into `approval` without this report on disk**.

## When to invoke

- Inside `/next`, phase 3 (mandatory before approval).
- Standalone whenever a plan has drifted from the code it was written against, or a spec changed
  under an in-flight plan.

Do **not** use it to *fix* anything — it is a detector. Findings route back to the plan (revise) or
to execution (as explicit tasks), never to a silent edit here.

## What to check (the consistency matrix)

- **Plan ↔ intent:** Does the plan cover every acceptance criterion of the stated goal? Any
  criterion with no corresponding plan step is a **coverage gap**. Any plan step with no backing
  criterion is **scope drift** (gold-plating) — flag it.
- **Plan ↔ code:** Do the plan's `path:line` citations still resolve? Does a referenced symbol /
  file / API still exist and have the shape the plan assumes? A stale citation is a **grounding
  failure** (the same class `verify-plan-evidence.mjs` hard-fails at commit).
- **Plan-internal:** Contradictory steps, an ordering that can't hold (step N needs step M's output
  but runs first), or an evidence dimension left uncited.
- **Intent ↔ code:** Does the code already do what the plan proposes to add? (grep-before-build —
  retire anything already done.)

## Steps

1. Read all three artifacts. Resolve every `path:line` citation in the plan against the working
   tree; note any that fail.
2. Walk the consistency matrix above. For each finding record: **type** (coverage-gap / scope-drift
   / grounding-failure / contradiction / already-done), **location** (`path:line` or plan step),
   **severity** (blocker / warning), and a one-line **so-what**.
3. **Write the report** to a file (e.g. under `config.plan.dirs.worktrees`, alongside the plan, or
   the run's scratch dir). The `/next` gate requires this file to advance:
   `node .harness/scripts/next-phase-gate.mjs advance approval --report <this-report-path>`.
4. If there are **blocker** findings, the honest outcome is *do not approve* — loop back to the
   plan phase, not forward. `/analyze` finding nothing on a non-trivial change is itself suspect
   (mirror the adversarial-reviewer's zero-findings skepticism): re-read before declaring clean.

## Output shape

```markdown
# /analyze report — <plan name>
**Verdict:** <clean | findings (N blockers, M warnings)>

## Findings
- [blocker] grounding-failure — plan step 3 cites `lib/x.mjs:42`, which no longer exists.
- [warning] scope-drift — plan step 6 adds caching not required by the goal.

## Coverage
- Criterion "<X>" → plan step <n> ✅ / ❌ (gap)
```

## Related

- [[next]] — the gated spine this runs inside (phase 3, gates entry to `approval`).
- `.harness/scripts/audits/verify-plan-evidence.mjs` — the commit-time grounding gate; `/analyze`
  is the earlier, broader read that catches drift before code exists to commit.
- `.harness/subagents/adversarial-reviewer.md` — the same must-find-issues posture, applied to code.
