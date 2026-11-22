# System Invariants — registry & Protection Matrix

Properties that must always hold in a kaizen-driven repo. Each invariant states **what it protects against**
and **where it is enforced** — and unlike prose guidance, most name a *mechanical* enforcement point. Adapted
from [`liza-mas/liza`](https://github.com/liza-mas/liza) `INVARIANTS.md`.

**Enforcement legend:** `gate` = a pre-commit/pre-push audit in `gates/core.gates.json`; `hook` = a git hook;
`subagent` = an adversarial review role; `contract` = a behavioral rule in `memory/rules.md`;
`script` = a verification script.

---

## 1. System integrity (Tier 0 — inviolable)

| ID | Invariant | Protects against | Enforced |
|----|-----------|------------------|----------|
| T0.1 | No unvalidated success | premature completion, undetected failure | gate `verify.mjs` (honest-abstain) + contract |
| T0.2 | No fabrication — claims verified against reality | hallucination, phantom fixes, false status | gate `verify-plan-evidence.mjs` (citation grounding) + contract |
| T0.3 | No test corruption | greenwashing, silent defect acceptance | gate `verify-test-gaming.mjs` + subagent adversarial-reviewer |
| T0.4 | No silent override | un-audited escape hatches | gate `verify-decision-log.mjs` + contract |
| T0.5 | No secrets exposure | credential leakage | gate `verify-secrets.mjs` (staged) |
| T0.6 | Worktree-first on default branch | dirty main, un-isolated substantive work | hook (branch guard) + `AGENTS.md` invariants 1–2 |
| T0.7 | Never `--no-verify` | bypassing the gate chain | hook (pre-commit/pre-push) + constitution §1 |

## 2. Epistemic integrity (Tier 1 — waiver required)

| ID | Invariant | Protects against | Enforced |
|----|-----------|------------------|----------|
| T1.1 | Assumption budget (≥3 critical / 1 irreversible → BLOCKED) | unbounded guessing, hidden dependencies | contract `memory/rules.md` |
| T1.2 | Intent Gate (observable success + validation stated first) | vague goals propagating into execution | contract |
| T1.3 | Source declaration (verify reads; tag reasoning) | untraced reasoning, stale-read edits | contract |
| T1.5 | Anti-gaming (outcome over letter) | metric-gaming, interpretation-narrowing | contract + subagent adversarial-reviewer |

## 3. Supply chain & dependencies

| ID | Invariant | Protects against | Enforced |
|----|-----------|------------------|----------|
| S.1 | No unverified/hallucinated dependency | supply-chain slop, typosquats | gate `verify-slopcheck.mjs` |

## 4. Learning loop

| ID | Invariant | Protects against | Enforced |
|----|-----------|------------------|----------|
| L.1 | Every real bug yields a prevention artifact (postmortem + guardrail + automation path) | repeating the same class of failure | gate `verify-learning-loop.mjs` |

## 5. Portability

| ID | Invariant | Protects against | Enforced |
|----|-----------|------------------|----------|
| P.1 | Zero hardcoded stack/host/repo couplings — each is a named config key | plumbing masquerading as a harness | constitution §4 + `config.schema.json` |
| P.2 | Memory lives in-repo, committed | context lost across resets / host drift | constitution §5 |

## 6. Lifecycle integrity (install · usage · removal)

The two failure classes the lifecycle wargames (`docs/wargames/lifecycle-wargames-2026-07-10.md`) scoped to:
**accidental permanent loss** and **no-escape stuck states**. Each invariant below names its *mechanical*
backstop — a script plus a red-first test — so the class has a tested home, not just prose.

| ID | Invariant | Protects against | Enforced |
|----|-----------|------------------|----------|
| I.1 | **Install is atomic / crash-safe** — a partial or interrupted install never bricks git or half-wires hooks, and a corrupt `config.json` fails closed with an actionable message (never a raw stack) | half-wired hooks, dangling bootstrap commits, a truncated config bricking every git op | script `cli/commands/init.mjs` (preflight refuse on detached-HEAD/mid-merge/rebase; `lib/install-guard.mjs` signal rollback; atomic `writeConfig`) + drivers `pre-commit.mjs`/`pre-push.mjs` (`loadConfigOrExit`) · tests `test/install-atomicity.test.mjs`, `test/config-corruption.test.mjs`, `test/install-block-e2e.test.mjs` |
| I.2 | **Install/usage never silently weakens enforcement** — re-init preserves a hand-tightened posture, an orphaned chained control turns `doctor` red, and a leftover bootstrap nonce self-heals | silent re-init downgrade of `branchGuard`/`security`/`guard`; a relied-on control that vanishes; a replayable stale nonce | script `cli/commands/init.mjs` (re-init deep-merge preserve) + `doctor.mjs` (orphaned-control FAIL + stale-nonce WARN) + `lib/bootstrap-nonce.mjs` (TTL) · tests `test/reinit-preserve.test.mjs`, `test/orphaned-control.test.mjs`, `test/nonce-ttl.test.mjs` |
| R.1 | **Removal never destroys gitignored or uncommitted audit state without explicit confirmation**, and is symmetric to install | permanent loss of the gitignored `events.jsonl` spine / uncommitted decisions; overlays left pointing at a removed harness | script `cli/commands/uninstall.mjs` (uncommitted-content guard, gitignored-state snapshot, TTY confirm, registry-driven overlay/payload strip) · tests `test/uninstall-safety.test.mjs`, `test/uninstall-symmetry.test.mjs` |

---

## Cross-reference Protection Matrix

When a change's **blast radius** intersects a threat category below, consult the listed invariants **before**
acting and apply the **tier-appropriate response**:

- **T0 invariant** → non-overridable. Halt per `memory/rules.md`; do not ask for confirmation.
- **T1 invariant** → proceed only with an explicit waiver + rationale (and a decision-log entry if it overrides a gate).
- **All others** → surface the specific invariant, explain the conflict, ask for direction. Never silently proceed.

| If the change touches… | Check invariants | Typical enforcement to expect |
|------------------------|------------------|-------------------------------|
| Test files / assertions | T0.1, T0.3 | test-gaming gate + adversarial-reviewer |
| A plan file or its evidence citations | T0.2 | plan-evidence grounding gate |
| A gate, hook, or `core.gates.json` | T0.4, T0.7, L.1 | decision-log gate; never weaken fail-closed |
| Anything that could print/commit a secret | T0.5 | staged secret-scan gate |
| Branch / worktree / commit flow on default branch | T0.6, T0.7 | branch-guard hook |
| Adding a dependency | S.1, T1.1 | slopcheck gate; assumption budget |
| A fix for a real bug | L.1, T2.4 | learning-loop gate (needs a prevention artifact) |
| A stack/host/path literal in portable code | P.1 | config schema — must be a named key, not a literal |
| Durable context / memory location | P.2 | must be in-repo, not host-local |
| `kaizen init` / the install flow (hook wiring, config write, git state) | I.1, I.2 | preflight refuse + signal rollback + atomic write; re-init deep-merge preserve; doctor orphan/nonce checks |
| `kaizen uninstall` / removing the harness | R.1 | uncommitted-content guard + gitignored-state snapshot + TTY confirm + symmetric strip |

**Test:** *"Does this change preserve every invariant it touches?"* If not, name the invariant and apply the
tier-appropriate response. This registry documents enforcement that already exists — it does not replace the
gates; it routes you to them.

<!--CANARY: THICKET-->

