---
name: agent-protocol
description: Multi-agent backlog-draining protocol. Triage → ground → advisor → cluster → spawn one wave → serialize-integrate → run to exhaustion → retro-of-retros → document skips. Delegates independent work to a fleet of agents that each plan+implement in a worktree, then integrates their branches serially through the orchestrator with adversarial verification.
triggers:
  - "/agent-protocol"
  - "agent protocol"
  - "drain the backlog with agents"
  - "run a wave of agents"
  - "orchestrate this with subagents"
  - "fan out agents to clear the backlog"
---

# agent-protocol

A named, repeatable mechanism for draining a backlog with a fleet of delegated agents:
triage every doable item, cluster the independent ones, have a stronger reviewer sharpen
the plan, delegate each cluster to an agent that **plans + implements**, integrate results
**serially through the orchestrator**, run waves **to exhaustion**, then close with a
**retro-of-retros** that improves the workflow itself.

Exists because parallel delegation silently degrades without discipline: agents self-merge
into races, ship confident no-ops, and drop work on timeouts that looks like failure but
isn't. The phases and invariants below are the scar tissue that keeps a wave honest.

This skill is the harness-native form. All stack specifics resolve through
`.harness/config.json` and `AGENTS.md` — never assume a fixed toolchain command.

## When to invoke

- You have a **backlog of independent items** — open plans in the active plans dir, open
  findings under the learning-loop dirs, a TODO/audit sweep — where several can proceed
  without blocking each other.
- The work benefits from **parallelism + independent verification**, not one linear edit.
- The user has **explicitly opted into multi-agent orchestration** — this spends real
  tokens across many request streams. Do not self-trigger it for ambient work.

Do **not** invoke for a one- or two-file change you can finish inline, or when every
remaining item is genuinely gated/serial.

## Grounding (read once at the top of the run)

- Read `AGENTS.md` and `.harness/config.json`. Resolve, from config:
  - `defaultBranch` — the branch agents must **never** commit to directly (worktree-first).
  - `verify` contract — the real `test`/`lint`/`build`/`e2e`/`healthcheck` checks, run via
    `.harness/scripts/verify.mjs`. This is the marquee gate; there is no hardcoded command.
  - `plan.dirs.active` / `plan.dirs.worktrees` / `plan.dirs.done` — plan lifecycle folders.
  - `plan.claimsFile` — the worktree claims ledger (who owns what).
  - `plan.evidenceHeading` and `plan.dimensions` — the evidence section every plan carries
    and the **configured** dimensions to cite (see phase 5; do not hardcode a dimension count).

## The nine phases

### 1. Triage
Enumerate **every** open item across the repo's backlog surface — open plans in the active
plans dir, open findings under the learning-loop dirs (`docs/audits`, `docs/errors`, or the
`.harness/archive/*` equivalents per config), and any explicit TODO/audit sweep the scope
names. Classify each:
- Open worktree list: !`git worktree list --porcelain`
- **Do-now** — unblocked, positive cost-benefit, fits a disjoint domain.
- **Skip** — gated (product/data/infra), low cost-benefit, or infeasible. **Document the
  reason and a rough score for every skip.** Skips are recorded, never silent (phase 9).
- **Route-to-config** — anything whose only effect is scanner/linter noise goes to the
  relevant exclusion/suppression config with a scoped rationale, not to an agent task. Never
  fake a suppression to make noise disappear; if the mechanism can't be validated (server
  down, gate unavailable), **document the deferral** and log it under `.harness/archive/decisions/`.

### 2. Ground (grep-before-build)
Before composing any wave:
- `grep`/read each do-now candidate's marquee target — **retire anything already done.**
- Confirm the named gap is **real** — don't trust a ledger entry blindly.
- Confirm a **green base tip**: `git log -1`, run the verify contract
  (`.harness/scripts/verify.mjs`), and **pin the commit** — every agent branches from it.
- Identify **uncontrolled / live agents** (`git worktree list --porcelain`) and mark their
  domains **off-limits** for this wave.

### 3. Advisor
Write the plan out, then call `advisor()`. **Adopt its blocking fixes before spawning.**
The advisor sees the whole transcript and catches sequencing/concurrency errors the plan
glosses over (it is the mechanism that forces the serialize-merge model and pulls a
hard-fail gate flip out of a concurrent wave).

### 4. Cluster
Partition do-now items into **disjoint-domain clusters** — *no two clusters edit the same
file*. Watch shared/ratchet files: manifests (`package.json`, lockfiles), baseline/budget
JSON, registries, CI workflows, and `plan.claimsFile`. Assign a model per cluster:
- **Default: omit the override and inherit the session model.**
- **Downshift to a cheaper/faster model** only for squarely mechanical or docs-only clusters
  (ratchet edits, config wiring, standard authoring).
- **Keep the strong model** for judgment-heavy spikes, behavioral-regression-risk refactors
  (need differential evidence), and security / gate-hardening / latent-gap detection.

**Defer** clusters that touch a live agent's domain or share a ratchet file with another
cluster — run them in a later wave.

### 5. Spawn (one wave)
Launch the wave's agents **concurrently**, each with a self-contained prompt (fresh contexts
inherit no memory or prior-wave scar tissue — the prompt must carry every rule) enforcing
the per-agent lifecycle:
1. `git worktree add <wt> -b <branch> <PINNED_BASE>` and record the claim in `plan.claimsFile`.
2. Bootstrap the worktree per the repo's init path (`.harness/` scripts / `AGENTS.md`).
3. Write a plan inside the worktree under `plan.dirs.worktrees`, including the evidence
   section named by `plan.evidenceHeading`. **Cite every dimension configured in
   `plan.dimensions`** (currently the core set — Tests / shift-left, Reused patterns /
   grounding, Security — but read config; the list is dynamic) with an **inline `path:line`
   citation that resolves against the working tree**, or an explicit `N/A — reason`. A
   hallucinated citation hard-fails the commit.
4. Implement — stay **strictly in-domain**.
5. **Verify in-worktree**: run the full `.harness/scripts/verify.mjs` contract **plus the
   cluster's own marquee adversarial gate, run explicitly.** A "changed/related-only" check
   is a *subset* of the full gate — passing it is necessary, not sufficient. Do not use the
   remote/CI gate as a serial discovery probe; run the push-only checks locally first.
6. Commit plan+code on the branch with **real hooks** (never `--no-verify`).
7. **Return `BRANCH READY: <path> | <branch> | <summary> | gates: <passed>`** — **do NOT
   self-merge.** Return `SKIP: <reason + cost-benefit>` if infeasible.

If an agent writes an incident/RCA note, it must **register it in the same commit** so it
doesn't block siblings on shared default-branch gates.

A returning agent **self-verifies** (runs its gates) but never **self-approves** — approval
is a *separate role* (phase 6). **Doer ≠ reviewer**: no agent's own work is the sole thing
gating its own merge. This is the fleet form of Liza's per-task doer/reviewer pairing — the
doer produces the branch; a distinct reviewer (the orchestrator, or a dedicated reviewer
agent for significant work) approves it.

### 6. Serialize integration + review quorum (the orchestrator's job)
Merge branches **one at a time** through yourself — never let agents self-merge when an
uncontrolled agent shares the default branch:
- `--no-ff` merge one branch, then **verify the default branch is green** (run the verify
  contract) before the next.
- **Adversarially review every returned branch** — agents return confident no-ops. Run the
  branch's marquee gate yourself; don't trust the summary. Confirm the *mechanism* is real,
  not just that a file changed.
- **Review quorum, scaled to blast radius.** *Standard* cluster → **1 reviewer** (the
  orchestrator's adversarial pass above). *Significant/architectural* cluster — security,
  gate-hardening, behavioral-regression-risk, or a wide blast radius (consult the Protection
  Matrix, `.harness/INVARIANTS.md`) — requires **2+ independent reviewers**. If reviewers
  split, the branch is **`partially_approved`**: **do not merge** — surface the disagreement
  and escalate (reframe or ask), never average it away. Impact discovered *mid-review* that
  lifts a cluster into "significant" escalates its quorum on the spot.
- **Provider diversity (soft, L5).** When `.harness/config.json → agents` lists more than one
  provider and `review.providerDiversity` is enabled, **prefer a reviewer of a different
  provider than the branch's author** — cross-model review defeats shared blind spots. Soft
  preference, never a hard gate: a single-provider repo simply reviews with what it has.
- **Hold, don't stack**, if a contended index is locked or a sibling left the default branch red.

### 7. Run to exhaustion
Repeat phases 4–6 in waves until the unblocked backlog is **drained** or every remaining item
scores low cost-benefit. **Re-ground (phase 2) at the top of each wave** — earlier waves may
have closed or unblocked later items.

### 8. Retro-of-retros
A read-heavy synthesis across **all** wave reflections + this run's integration notes:
extract cross-wave patterns the per-wave retros missed and turn them into concrete
workflow/standard/memory improvements. Append the run's retro under `.harness/archive/retros/`,
and **promote durable heuristics into `.harness/memory/procedural/`** — that is the home that
survives context resets (per `AGENTS.md`); a session-scoped note evaporates on compaction.

### 9. Document & close
- Record every **skip** with its reason (and score) on the backlog surface it came from.
- Move shipped plans `plan.dirs.worktrees` → `plan.dirs.done` and clear their entries from
  `plan.claimsFile`; repoint any references so docs checks stay green.
- Log any gate override during the run under `.harness/archive/decisions/` — an override that
  leaves no trace is forbidden.
- Run the repo's closeout/verify pass and confirm the default branch is green.

## Invariants (learned empirically — violate these and the run silently degrades)

1. **Serialize the merge when you don't own every agent.** Self-merge only ever worked
   because prior waves controlled the whole environment. With an uncontrolled agent on the
   shared default branch, agents return "branch ready" and the **orchestrator** integrates.

2. **Adversarially verify every deliverable — agents ship confident no-ops.** A suppression
   put under the wrong config key, or an enumeration line omitted so every valid entry is
   inert, will ship silently. Always run the agent's own marquee gate and confirm the
   mechanism actually takes effect.

3. **Timeouts / connection-drops ≠ failure — inspect the worktree.** An agent that died
   mid-response may have finished and committed, or finished but *not* committed. Read the
   worktree git state for ground truth; commit it yourself if the work is done and correct.

4. **Verify the agent's judgment calls against primary sources.** A `Status: IN_PROGRESS`
   line can *look* unshipped while `git log` shows the feature already merged. Check git
   history before trusting **or** overriding a judgment call.

5. **New tooling installed in a worktree may need materializing on the default branch.** A
   worktree's dependency tree is not always the main checkout's. After merging a new dep,
   install on the default branch so local gates resolve the binary.

6. **Reconcile cross-cluster semantic coupling on the integrated tree.** Even disjoint
   *files* can couple semantically — one cluster refactors a module, another baselines that
   module's score against the pre-refactor version. Re-measure such floors on the **merged**
   tree, not in either worktree.

7. **Manual file deletes break the reference graph — use the plan-move path.** Deleting a
   plan stub by hand leaves dangling references that fail docs checks; the move helper
   rewrites them. If a delete already happened, repoint every reference before committing.

8. **Never `git add -A` / `git add .` on the shared default branch — stage explicit paths.**
   A concurrent agent may write its in-progress work into the *main checkout's* working tree
   (not just its own worktree), and `-A` sweeps it into your commit. Stage the exact files
   you authored. Re-check the working tree is yours right before every commit when another
   agent is live. If contamination already happened, `git reset --soft` + `git restore
   --staged <their-files>` preserves their uncommitted WIP while you re-commit only yours —
   **never `--hard`.**

9. **Hypothesis exhaustion — reframe, don't re-spawn.** When a cluster's agent returns
   `SKIP`/failure **twice on the same framing**, do **not** launch a third agent at the same
   task unchanged (the Ralph-Wiggum loop — blind persistence produces confidently wrong
   results). Two genuine failures mean the *framing* is wrong: re-scope the cluster, split it,
   or escalate to the user. This is the fleet enforcement of the contract's hypothesis-exhaustion
   rule (`.harness/memory/rules.md:115`).

Corollary integration gotchas:
- A **rejected pre-merge hook leaves the merge staged-but-uncommitted** — `git merge --abort`
  before re-merging the corrected branch.
- To fold an orchestrator fix into an agent's commit, **`git reset --soft HEAD~1` + re-commit**
  (plan+code together) — never `git commit --amend` a single file, or the plan-evidence gate
  false-fails (it diffs staged-vs-HEAD and won't see the already-committed plan).

## Related

- `AGENTS.md` — session-start invariants, worktree-first, verify contract, learning loop.
- `.harness/config.json` — `verify`, `plan`, `defaultBranch`, learning-loop dirs.
- `planmax` skill — the plan→score→advisor→implement loop each spawned agent runs inside.
