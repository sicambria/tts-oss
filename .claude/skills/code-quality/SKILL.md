---
name: code-quality
description: A reuse / simplification / altitude assessment pass over a change — is this the smallest correct code at the right level of abstraction, reusing what exists, or is it duplicated, over-engineered, or pitched at the wrong altitude? Quality only; it does not hunt for correctness bugs (that is /red-team and /code-review).
context: fork
agent: Explore
background: false
triggers:
  - "/code-quality"
  - "assess code quality"
  - "is this over-engineered"
  - "review for simplification"
---

# code-quality

A methodology skill: judge a change on **fit**, not correctness — does it reuse existing patterns, sit at the
right altitude, and carry no more machinery than the problem needs? It is the constructive, quality-only lens
that the `reviewer` subagent applies (`.harness/subagents/reviewer.md`), run on demand at authoring time. It
deliberately does **not** look for bugs — that is [[red-team]] / `/code-review`; conflating the two dilutes both.

Exists because agents systematically over-produce: unrequested abstractions, an interface with one
implementation, config for a constant, a new helper where an existing one fits (FM-COD-10 / FM-COD-12,
`.harness/reference/failure-modes.md:73`). Quality here is measured *downward* — the best change is the one that
adds the least surface while fully solving the approved problem (Scope Discipline + Minimality Ladder,
`.harness/memory/rules.md:68`).

## When to invoke

- Before committing a non-trivial change, to check it against the Minimality Ladder before it calcifies.
- When a diff *works* but feels large, clever, or duplicative and you want a structured second look.
- Assessing a subagent's or contributor's branch for reuse/simplification before integration.

Do **not** invoke to find correctness bugs (use [[red-team]] or `/code-review`), and do not invoke on a change
already known to be a minimal FAST-PATH edit (`.harness/memory/rules.md:121`) — the assessment would only
confirm what is already true.

## Steps

1. **Restate the approved problem in one sentence.** Quality is relative to intent — a change can be beautiful
   and still be gold-plating if it solves more than was asked (Scope Discipline, `.harness/memory/rules.md:68`).

2. **Reuse check — does this already exist?** Grep for the pattern, helper, or type before accepting new code.
   The Minimality Ladder rungs, in order: (1) does it need to exist at all? (2) stdlib/platform, (3) existing
   code/helper, (4) an installed dependency, (5) minimal custom code (`.harness/memory/rules.md:68`). Take the
   first rung that holds; a lower rung chosen for taste is a finding.

3. **Altitude check — right level of abstraction?** Is logic pitched too low (inline duplication that wants a
   helper) or too high (a framework for one caller, an interface with a single impl, premature generalization)?
   Name the mismatch and the corrected altitude.

4. **Subtraction pass — what can be deleted?** For each added construct (param, flag, layer, abstraction) ask
   *what breaks if it is removed?* If nothing, remove it. Dead branches, unused config, speculative extension
   points, and comments that restate the code all go.

5. **Recent-changes pass — does the diff respect its own history?** Look at the files the change touches
   as they were *before* this diff (git log / git blame on the touched hunks): was the surrounding code
   recently simplified, migrated, or deliberately left alone? A change that re-complicates a just-simplified
   helper, revives a just-deleted pattern, or fights the direction of the last two commits on those lines
   is a finding even if it looks minimal in isolation. Prefer extending the recent trajectory over
   re-litigating it; if the trajectory itself is wrong, that is a separate approved problem, not a drive-by.

6. **Consistency check — does it read like its neighbors?** Match surrounding naming, error-handling idiom, and
   comment density (a change that reads as foreign imposes a permanent tax on the next reader).

7. **Report as ranked, actionable findings.** Each: *file:line → the issue → the smaller/reused/right-altitude
   alternative.* Distinguish must-fix (violates minimality/reuse) from optional polish. If the change is already
   minimal and well-fitted, say so plainly — a clean bill is a valid result (unlike a bug review, quality has no
   "zero findings = failed" rule).

## Related

- `.harness/subagents/reviewer.md` — the review-time role that applies this constructive quality lens.
- [[red-team]] / `/code-review` — the correctness-hunting counterparts (this skill is quality-only).
- `.harness/memory/rules.md` — T2.3 Scope Discipline & Minimality Ladder, the standard this skill measures against.
- `.harness/reference/failure-modes.md` — FM-COD-10 / FM-COD-12 (drive-by complexity, unrequested abstractions).
