# Agent Failure-Mode Reference (design artifact — NOT hot-loaded)

**Purpose:** the research provenance behind the tiered behavioral contract in `../memory/rules.md`.
**Not for per-session agent consumption** — this file exists to *justify and maintain* the rules, at zero
runtime context cost. Agents load `rules.md` (the countermeasures); they read this only when *editing* the rules.

Adapted for kaizen from the failure-mode catalog in [`liza-mas/liza`](https://github.com/liza-mas/liza)
(`contracts/CONTRACT_FAILURE_MODE_MAP.md`), which sources it from:

- **MAST — Multi-Agent System Failure Taxonomy** (Berkeley, 2025): 14 modes distilled from 1,600+ multi-agent traces.
- **LLM behavioral research** (2024–2025): sycophancy, deception, hallucination studies.
- **Code-generation studies** (Da et al. 2023, Xia et al. 2024): bug introduction, incomplete refactoring, test corruption.
- **Instruction-following benchmarks** (AgentIF, 2025): constraint failures, tool violations.

> **Efficacy caveat.** A clause covering a failure mode demonstrates the rule *exists*, not that it *changes
> behavior under pressure* — this is a coverage map, not a measured failure-rate reduction. kaizen's real
> backstop is the **mechanical gate chain** (`../gates/core.gates.json`); the contract is the first line, the
> gates are the last. Known prompt-level ceilings (inherited from Liza): context-degradation detection relies
> on agent self-monitoring; alignment-faking is not solvable at the prompt level; assumption-counting can be
> gamed without an integrity backstop.

Each mode has an ID (`FM-*`) that a rule in `rules.md` cites, plus how kaizen answers it — via the **contract**
(a rule), a **gate** (mechanical, in `core.gates.json`), or a **subagent** (adversarial review).

---

## FC1 — Specification & system design (≈42% of MAS failures)

| ID | Failure mode | kaizen countermeasure |
|----|--------------|-----------------------|
| FM-1.1 | Disobey task specification | contract: Intent Gate + Definition-of-Ready (rules.md T1) |
| FM-1.2 | Disobey role specification | contract: subagent role prompts (`../subagents/`) |
| FM-1.3 | Step repetition (~17%) | contract: Stop Trigger — same fix/command twice without new rationale |
| FM-1.4 | Loss of conversation history | contract: re-read-after-compaction (Stop/PreCompact hooks) + tiered `memory/` |
| FM-1.5 | Unaware of stopping conditions | contract: Definition-of-Done + Stop Triggers (rules.md) |

## FC2 — Inter-agent misalignment (≈37%)

| ID | Failure mode | kaizen countermeasure |
|----|--------------|-----------------------|
| FM-2.1 | Conversation reset | contract: memory in-repo, survives resets (constitution §5) |
| FM-2.2 | Fail to ask for clarification (~12%) | contract: DoR — ambiguity → clarify, never guess |
| FM-2.3 | Task derailment | contract: Scope Discipline + Atomic Intent (rules.md T2) |
| FM-2.4 | Information withholding | contract: Omission = deception (rules.md T1) |
| FM-2.5 | Ignored peer input / shared-model blind spot | contract: agent-protocol orchestrator serialization + doer≠reviewer pairing, quorum, and **provider diversity** (L5/L7 — a different-provider reviewer, soft; `review.providerDiversity`) |
| FM-2.6 | Reasoning-action mismatch (~14%) | contract: exposed reasoning with tagged assumptions (rules.md T1) |

## FC3 — Task verification (≈21%)

| ID | Failure mode | kaizen countermeasure |
|----|--------------|-----------------------|
| FM-3.1 | Premature termination | contract: DoD checklist; gate: `verify.mjs` honest-abstain (`human_needed`) |
| FM-3.2 | No / incomplete verification | contract: "validation must exercise the changed behavior"; skill: `/verify` |
| FM-3.3 | Incorrect verification (test-gaming) | **gate: `verify-test-gaming.mjs`**; subagent: adversarial-reviewer |

## Behavioral — sycophancy / deception / hallucination

| ID | Failure mode | kaizen countermeasure |
|----|--------------|-----------------------|
| FM-SYC | Excessive agreement / softening critique | contract: No-Cheerleading + Direct-Response (rules.md T3) |
| FM-DEC-1 | Claiming success without validation | contract: T0 — No Unvalidated Success; gate: `verify.mjs` |
| FM-DEC-2 | Post-hoc rationalization | contract: Post-Hoc Discovery Protocol (rules.md T1) |
| FM-DEC-3 | Concealing difficulty / silent failure | contract: Struggle Protocol (rules.md T1) |
| FM-HAL-1 | Fabricating files / APIs / configs | contract: T0 — No Fabrication; **gate: `verify-plan-evidence.mjs` citation grounding** |
| FM-HAL-2 | Inventing file contents without reading | contract: Source Declaration — verify read occurred (rules.md T1) |

## Code generation

| ID | Failure mode | kaizen countermeasure |
|----|--------------|-----------------------|
| FM-COD-1 | Introducing bugs while "fixing" | contract: Root-Cause-Before-Symptoms (rules.md T2) |
| FM-COD-9 | Test corruption to pass CI | contract: T0 — No Test Corruption; **gate: `verify-test-gaming.mjs`** |
| FM-COD-10 | Drive-by edits / speculative complexity | contract: Scope Discipline + Minimality Ladder (rules.md T2) |
| FM-COD-12 | Unrequested abstractions / boilerplate | contract: no interface-with-one-impl (rules.md T2) |
| FM-SUPPLY | Unverified / hallucinated dependencies | **gate: `verify-slopcheck.mjs`** |

## Process, recovery & gaming

| ID | Failure mode | kaizen countermeasure |
|----|--------------|-----------------------|
| FM-REC-2 | Continuing after repeated tool failures | contract: Stop Trigger — tool fails 3× |
| FM-REC-3 | Not learning from violations | contract: same-rule-twice → halt; **gate: `verify-learning-loop.mjs`** |
| FM-REC-4 | Fixing symptom not root cause | contract: RCA-before-symptoms (rules.md T2) |
| FM-REC-5 | Systemic failure pattern goes undetected until post-hoc | contract: stop-triggers log `anomaly` events; **script: `ops/circuit-breaker.mjs`** (live, observation-only pattern trip → human) |
| FM-GAM-1 | "Technically compliant", intent violated | contract: Anti-Gaming Clause (rules.md T1) |
| FM-GAM-3 | Collapsing assumptions to fit a budget | contract: count leaf assumptions (rules.md T1) |
| FM-GAM-4 | FAST-PATH boundary exploitation (mislabeling a risky change as trivial to skip ceremony) | contract: FAST PATH eligibility + NOT-eligible list (rules.md) |
| FM-GAM-6 | Prompt injection via code/data/tool output | contract: Prompt-Injection Immunity (rules.md T0) |
| FM-OVR | Silent gate override / escape hatch | contract: Overrides accountable (constitution §6); **gate: `verify-decision-log.mjs`** |
| FM-INIT-1 | Acting without ingesting the contract (read non-compliance) | contract: session-start canary — surface 4 marker words (hook-less providers); Claude: SessionStart hook; **gate: `verify-canary.mjs`** (marker integrity/drift) |

---

## Maintenance

When editing `rules.md`: keep every rule traceable to an ID here. When a new failure mode is documented,
add a row and either name the covering countermeasure or flag it as a gap to close (prefer a **gate** over a
rule wherever the check can be mechanical — kaizen's thesis is enforcement, not prose).
