# EXPERIENCE.md — identity-hygiene

Pilot domain for H2-4 (src: `harness2/core/library.py` — per-domain full-tree experience
library). Each entry is a **cue / lesson / evidence / confidence** record: the cue states when
the lesson applies, the lesson states what to do, the evidence cites behavioral proof (a gate
path, a test path, an incident note — never a summary claim), and the confidence states how
strongly the evidence supports reuse. An entry missing any of the four is incomplete and must
not be stored (`has_experience` completeness gate — enforced by the learning-loop schema
extension specified in `docs/plans/worktrees/h2-12478-library-ledger.md`, not by prose here).

## Lesson 1 — Detect host fingerprints structurally, not by username

- **cue:** A new gate must catch machine-specific identifiers in committed text on any machine,
  including CI where the runtime user is generic (`runner`).
- **lesson:** Match the absolute home-path *shape* (`/home/<user>/`, `/Users/<user>/`,
  `\Users\<user>\`) as the portable floor; treat the running host's own username/hostname as a
  best-effort machine-local bonus layer only.
- **evidence:** `docs/errors/2026-07-06-host-unique-identifiers-were-committable-and-committed.md`
  (67 identifiers across 8 files, nothing blocked them); the gate it produced,
  `.harness/scripts/lib/identity.mjs:38` (`HOME_PATH_RE`) with the runtime layer at
  `.harness/scripts/lib/identity.mjs:53` (`hostFingerprints`, degrades to null); round-trip
  coverage in `test/identity-scan.test.mjs:114`.
- **confidence:** high — the structural rule fires deterministically in CI; the incident's
  Prevention section records the full tree clean after the fix.

## Lesson 2 — Pair every detector with its write-time inverse in one module

- **cue:** A leak has a *generator* (a hook or scaffolder that re-emits the flagged pattern every
  run), so detection alone regrows the finding.
- **lesson:** Ship the redactor alongside the detector in the same module (`redactHostPaths`
  next to `scanLine`) so the two can never drift, and fix the generator at its write site.
- **evidence:** Same incident, Root Cause §2: `memory-capture.mjs` wrote `cwd`/`transcript_path`
  verbatim and auto-commit faithfully committed the leak; fix at `memory-capture.mjs:300`
  redacting via `distillEntry` (`memory-capture.mjs:120`); redact→scan round-trip test at
  `test/identity-scan.test.mjs:114`.
- **confidence:** medium-high — one incident plus its regression tests; re-confirm if a second
  generator-class leak appears in another domain.
