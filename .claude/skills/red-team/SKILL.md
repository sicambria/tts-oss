---
name: red-team
description: Adversarial test design — attack a change the way a hostile input, a careless caller, or a malicious actor would, before it ships. White-box (you know the code) and black-box (you only know the contract) attack passes that turn "it works" into "I tried to break it and here is what held."
context: fork
agent: general
background: false
triggers:
  - "/red-team"
  - "red team this"
  - "how could this break"
  - "attack this change"
---

# red-team

A methodology skill: deliberately try to **break** a change before declaring it done — enumerate the inputs,
states, and orderings its author did not consider, and prove each is either handled or a real defect. It is the
offensive complement to [[debugging]] (which is reactive) and to the `adversarial-reviewer` subagent
(`.harness/subagents/adversarial-reviewer.md`), whose core rule is that a review finding **zero** issues has
failed. This skill runs that stance *before* review, at authoring time.

Exists because "it worked in the demo" is exactly the failure this harness was built against: an agent confirms
the happy path and stops (premature termination / incomplete verification — FM-3.1 / FM-3.2,
`.harness/reference/failure-modes.md:52`). Red-teaming forces the unhappy paths into the open while they are
cheap to fix, and produces the evidence the Definition-of-Done demands (`.harness/memory/rules.md:66`).

## When to invoke

- Before shipping a change that touches control flow, parsing/validation, error handling, security/auth, or a
  boundary (exactly the FAST-PATH *NOT-eligible* list, `.harness/memory/rules.md:126`).
- When writing tests for new behavior and you want the *adversarial* cases, not just the confirming one.
- Reviewing someone else's (or a subagent's) diff and "it passes" is the only stated evidence.

Do **not** invoke for a pure-docs or pure-comment change with no runtime surface to attack — there is nothing to
break; say so rather than manufacturing ceremony.

## Steps

1. **State the contract you are attacking.** What does this code *promise* (inputs accepted, outputs
   guaranteed, invariants preserved)? You cannot find a violation without a spec to violate — if it is
   unstated, that ambiguity is the first finding (Definition-of-Ready, `.harness/memory/rules.md:64`).

2. **Black-box pass — attack the boundary blind.** From the contract alone, enumerate: empty / null / missing,
   maximum / overflow, malformed / wrong-type, duplicate, out-of-order, concurrent, and the classic injection
   surfaces (path traversal, shell/SQL/template, prompt injection via data — FM-GAM-6,
   `.harness/memory/rules.md:40`). Which promise breaks under each?

3. **White-box pass — attack what the code reveals.** Now read the implementation. For every branch: what input
   reaches the *other* branch? For every unchecked assumption (index, key exists, non-null, network succeeds):
   what makes it false? For every resource: what if it is exhausted or the operation is interrupted mid-write?

4. **Attack the tests themselves.** Would these tests still pass if the behavior were subtly wrong? A test that
   asserts nothing meaningful, or that was edited to accept the current output, is test-gaming (T0.3,
   `.harness/memory/rules.md:32`) — a finding, not a pass.

5. **Rank and resolve — every attack lands as handled-or-fixed.** For each attack: it is (a) correctly handled →
   pin it with a test; (b) a real defect → fix it (hand off to [[debugging]] for the root cause); or (c) out of
   scope → state *why* explicitly (never silently narrow the contract to dodge it — anti-gaming, T1.5,
   `.harness/memory/rules.md:56`).

6. **Report what held, not just what broke.** The output is "I attacked it with N vectors; M were handled
   (tests added), K were defects (fixed), J are out of scope because …" — evidence, not reassurance.

## Related

- `.harness/subagents/adversarial-reviewer.md` — the review-time enforcer of this same stance (zero findings = failed review).
- [[debugging]] — where a confirmed defect goes for root-cause analysis.
- [[verify]] — exercises the surviving change end-to-end after the attacks are resolved.
- `.harness/reference/failure-modes.md` — FM-3.1 / FM-3.2 (premature / incomplete verification) this skill counters.
