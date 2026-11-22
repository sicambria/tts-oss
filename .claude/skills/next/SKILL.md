---
name: next
description: The gated /next orchestration spine — drives one unit of work through plan → Phase-1 gate → /analyze → human approval → fresh-context executor subagents in worktrees → verify → adversarial review. Every transition is enforced by .harness/scripts/next-phase-gate.mjs, which BLOCKS (exit 1) an out-of-order jump or a missing precondition artifact. Use for a single non-trivial feature/change that deserves the full disciplined progression (distinct from agent-protocol, which fans a fleet across an independent backlog).
triggers:
  - "/next"
  - "run the next spine"
  - "gated plan to execution"
  - "phase-gate this work"
---

# next

The **enforced** `plan → phase1 → analyze → approval → execute` progression for one unit of
non-trivial work. Unlike a prose checklist, each transition calls
`.harness/scripts/next-phase-gate.mjs advance <phase>` — **the gate exits 1 and blocks** if you
skip a phase or the transition's precondition artifact is missing. The skill is the scaffold; the
gate script is the mechanism that bites.

## next vs agent-protocol

- **`/next`** — ONE unit of work, driven linearly through hard phase gates with a human approval
  in the middle. The state machine is the point.
- **`agent-protocol`** — a FLEET draining an independent backlog in parallel waves. No per-item
  approval gate; the discipline is serialize-integrate + adversarial verification.

Reach for `/next` when the risk is *shipping the wrong thing fast*; reach for `agent-protocol`
when the risk is *a backlog rotting because work is serial by habit*.

## Grounding (read once)

- `AGENTS.md` + `.harness/config.json` (`defaultBranch`, `verify`, `plan.dirs`, `plan.evidenceHeading`).
- The gate CLI: `next-phase-gate.mjs status | advance <phase> [--plan p] [--report p] | require <phase> | approve --by <who> | reset`.
- Subagent role cards under `.harness/subagents/` — `orchestrator`, `executor`, `verifier`,
  `reviewer`, `slopchecker`, `adversarial-reviewer`.

## The gated flow

Run `next-phase-gate.mjs status` at the top. Then, for each phase, **do the work first, then call
`advance` — the gate refuses the transition until the work's artifact exists.**

### 0. Reset (new unit of work)
`node .harness/scripts/next-phase-gate.mjs reset` — clears any prior run's state.

### 1. plan
`advance plan`. Write a plan under `config.plan.dirs.worktrees` with the
`## Standards & Guardrails Evidence` section (resolving `path:line` citations per every configured
`plan.dimensions` key). The **planmax** skill is the plan→score→advisor loop to run here.

### 2. phase1 — the Phase-1 pre-implementation gate (P1-6)
`advance phase1 --plan <path-to-plan>`. **BLOCKS unless the plan file exists AND carries the
evidence heading** — a bare stub is not a plan. This is the pre-implementation gate: no code before
a grounded plan.

### 3. analyze — cross-artifact consistency (`/analyze`)
Run the **analyze** skill: check the plan against the spec/intent and against the current code for
contradictions, missing coverage, and scope drift. Write its report to a file, then
`advance analyze`. (The report is what `approval` will require.)

### 4. approval — human gate (paired with the automated gate, never approval-only)
Present the plan + analyze findings to the human via `AskUserQuestion`. On a yes:
`node .harness/scripts/next-phase-gate.mjs advance approval --report <analyze-report-path>`
then `node .harness/scripts/next-phase-gate.mjs approve --by <human>`. **`advance approval` BLOCKS
without the analyze report on disk; the later `advance execute` BLOCKS without this recorded
approval** — the human gate is real, not advisory.

### 5. execute — fresh-context executor subagents in worktrees
`advance execute` (guard-budgeted — see below). Then spawn **fresh-context executor subagents**
(role card: `executor`), each in its own `git worktree` off the pinned base, each carrying the full
plan (fresh contexts inherit no memory). Executors implement strictly in-domain and return
`BRANCH READY` — they do **not** self-merge.

### 6. verify + review (before integration)
Per returned branch, run — in order, all must pass:
1. **verifier** — the full `.harness/scripts/verify.mjs` contract + the change's marquee gate.
2. **slopchecker** — supply-chain / dependency sanity (P1-7 direction).
3. **adversarial-reviewer** — must-find-issues; **zero findings HALTS** (a review that finds
   nothing is treated as incomplete, not a pass). Edge-case hunter.

The **orchestrator** integrates branches serially (`--no-ff`, re-verify green between merges),
never letting executors self-merge.

## Why the gate, not just prose

Roadmap anti-patterns call out *human-approval-only gates* and *advisory guardrails that log rather
than block*. `/next` pairs the human `approval` phase with `next-phase-gate.mjs`, which **refuses**
`execute` until approval is recorded — the automated refuse-on-fail the roadmap demands.

## requireGuard consumer (Debt #4)

`advance execute` calls `requireGuard(root, cfg, 'next:execute')`. It passes through today (not in
`config.guard.scaffolderCommands`); adding `"next:execute"` there makes `/next` the first real
`requireGuard` consumer, which lets roadmap Debt #4 flip `doctor`'s guard-check from WARN to FAIL.

## Related

- `.harness/scripts/next-phase-gate.mjs` — the enforced state machine (this skill's spine).
- `.harness/subagents/*.md` — the role cards spawned in phases 5–6.
- [[analyze]] — the consistency check run in phase 3.
- [[planmax]] — the plan-scoring loop run in phase 1.
- `agent-protocol` — the fleet/backlog sibling to this single-unit spine.
