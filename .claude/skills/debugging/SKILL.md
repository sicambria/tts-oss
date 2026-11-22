---
name: debugging
description: Structured root-cause-before-fix debugging — turn a symptom into a stated hypothesis, gather evidence that confirms or kills it, fix the cause (not the symptom), and leave a prevention trace. The disciplined counter to guess-and-check patching.
triggers:
  - "/debugging"
  - "debug this"
  - "why is this failing"
  - "find the root cause"
---

# debugging

A methodology skill: drive a bug from **symptom → hypothesis → evidence → root cause → fix → prevention**
instead of mutating code until the error disappears. It operates *within* the behavioral contract — it does
not relax it: T2.4 root-cause-before-symptoms (`.harness/memory/rules.md:72`), the "evidence contradicts the
working hypothesis → STOP" stop-trigger (`.harness/memory/rules.md:109`), and hypothesis-exhaustion —
two failed genuine attempts means the framing is wrong, reframe don't retry (`.harness/memory/rules.md:115`).

Exists because the most common failure mode of a coding agent under pressure is **fixing the symptom, not the
cause** (FM-COD-1 / FM-REC-4 in `.harness/reference/failure-modes.md:71`): a change that makes the error go
away while introducing a new bug, or that patches one call site of a defect that lives in three. Structured
debugging makes the cause explicit and testable before any edit lands.

## When to invoke

- A test, gate, or runtime behavior is failing and the cause is not yet *proven* (not merely guessed).
- A fix attempt already bounced — before a second attempt, to force a real hypothesis rather than a re-roll.
- An intermittent / "works on my machine" defect where the reproduction itself is the hard part.

Do **not** invoke for a change whose cause is already evident and proven — writing the hypothesis ceremony for
a one-line typo you can see costs more than it returns (that's a FAST-PATH change, `.harness/memory/rules.md:121`).

## Steps

1. **Reproduce first — a bug you cannot trigger, you cannot fix.** Capture the exact command, input, and
   observed vs. expected output. If you cannot reproduce it, that *is* the current task; say so, don't guess.

2. **State one falsifiable hypothesis.** Write it as: *"I believe the cause is X. If so, then Y will be true.
   I will check Y by Z."* Tag it `ASSUMPTION` until evidenced (`.harness/memory/rules.md:52`). One hypothesis
   at a time — a list of five guesses is not a hypothesis.

3. **Gather evidence that could KILL the hypothesis**, not just confirm it. Read the actual code/state
   (re-read, don't recall — Source Declaration, `.harness/memory/rules.md:51`); add a probe/log; bisect.
   If the evidence contradicts the hypothesis → **STOP**, discard it, return to step 2. Do not bend the
   evidence to fit.

4. **Confirm the root cause reaches the symptom.** Trace the mechanism end-to-end: *this* state produces
   *that* observable. If you cannot draw the line, you have a correlation, not a cause — keep going.

5. **Fix the cause, then sweep for siblings.** Apply the minimal change at the cause site (Minimality Ladder,
   `.harness/memory/rules.md:68`), then grep for the same defect elsewhere — a root cause usually has clones.

6. **Prove it — exercise the changed behavior.** Re-run the reproduction from step 1; it must now pass and
   the previously-green tests must stay green (Definition-of-Done, `.harness/memory/rules.md:66`). Running
   unrelated green tests is not proof (T0.1). Prefer a **new failing-first test** that pins the bug so it
   cannot silently return.

7. **Leave a prevention trace.** If this was a *real* bug (not a typo), the incident/learning loop applies —
   scaffold a note with a concrete guardrail + automation path (`AGENTS.md:39-43`), don't silently fix.

## Related

- [[verify]] — proves the fix exercises the real behavior end-to-end (step 6's mechanical companion).
- `.harness/memory/rules.md` — T2.4 root-cause, the stop-triggers, hypothesis-exhaustion this skill enforces.
- `.harness/reference/failure-modes.md` — FM-COD-1 / FM-REC-4 (symptom-not-cause), the modes it counters.
- [[red-team]] — the offensive complement: attack a change to *find* bugs before they ship.
