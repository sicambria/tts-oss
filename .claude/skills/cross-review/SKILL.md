---
name: cross-review
description: Cross-AI peer-review routing (P2-16) — fan the working diff out to configured external AI reviewers (Gemini/Codex/CodeRabbit or any diff-on-stdin CLI), rank each reviewer's output by file-grounded citations, and abstain human_needed when nothing is configured or no key is present. Advisory, config-driven, never a gate.
context: fork
agent: general
background: false
triggers:
  - "/cross-review"
  - "cross review this"
  - "peer review the diff"
  - "route this to gemini/codex/coderabbit"
  - "get a second AI opinion on the diff"
---

# cross-review

A named, config-driven, **honest-abstain** cross-AI peer review: gather the working diff → fan it out
to every configured reviewer → rank each reviewer's output by how many of its `path:line` citations
actually resolve against the tree → print the most-grounded first. This is the mechanism behind roadmap
item **P2-16** (cross-AI peer-review routing with file-grounded evidence weighting).

Named `cross-review`, **not** `/review`, on purpose — Claude Code ships a built-in `/review` (GitHub
PR) and `/code-review` (working diff). This routes to *other* AIs and leaves both built-ins intact.

Exists because a single model shares its own blind spots. Routing the same diff to an independent
provider (ideally a different vendor — see `config.review.providerDiversity`, L5) surfaces issues the
authoring model is structurally unable to see. Grounding the ranking in resolving citations keeps a
confident-but-hallucinated review from outranking a terse, correct one.

## When to invoke

- You want a second (or third) *independent* AI opinion on the current diff before it merges.
- A CI job wants one fail-closed entrypoint that abstains cleanly when no reviewer is configured.

Do **not** treat it as a verification gate — it runs no tests (see "Not a gate" below).

## Mechanism

```
node .harness/scripts/ops/review.mjs
```

Reads `config.review.providers` from `.harness/config.json`:

```jsonc
"review": {
  "providerDiversity": "soft",        // existing (L5) reviewer-diversity preference — untouched
  "providers": [                        // empty/absent ⇒ /cross-review abstains (human_needed)
    { "name": "gemini",     "cmd": "gemini review",      "keyEnv": "GEMINI_API_KEY" },
    { "name": "codex",      "cmd": "codex exec review",  "keyEnv": "OPENAI_API_KEY" },
    { "name": "coderabbit", "cmd": "coderabbit --plain", "keyEnv": "CODERABBIT_TOKEN" }
  ]
}
```

- **`name`** (required) — label in the report + events.
- **`cmd`** (required) — a command that reads a unified diff on **stdin** and prints findings on stdout.
- **`keyEnv`** (optional) — an env var that must be non-empty for this provider to run. Absent ⇒ the
  provider always runs (e.g. a local model). Present-but-unset ⇒ the provider is **skipped** (abstains),
  never silently passed.

The diff reviewed is everything on the current branch since it diverged from `defaultBranch`
(`git diff --merge-base <defaultBranch>`, falling back to `git diff HEAD`).

**Honest-abstain (fail-closed, mirrors `/deploy`):**
- No usable providers configured → logs an `abstain` event, prints `human_needed`, exits **1**.
- Providers configured but **every** one skipped for a missing key-env → also **abstain, exit 1** (a
  review that ran nothing is not a pass).
- **Empty diff** → there is genuinely nothing to review → **exit 0** with `nothing to review`, logged as
  `status:noop`. This is a determinate complete answer, not a failure and not an abstain.

**Security:** the diff and filenames are passed to each reviewer on **stdin** — never interpolated into
the shell command. The `cmd` string is operator-authored committed config (same trust model as
`config.deploy.cmd`). A diff full of shell metacharacters cannot alter what command runs.

## Not a gate (by design)

`/cross-review` is **advisory** and is deliberately **not** wired into pre-commit. AI-review-only
verification with no test execution is a documented anti-pattern; this command never claims to *verify*
code. Its output is ranked opinion, weighted by citation grounding — weigh it, don't obey it. The
verify contract (`.harness/scripts/verify.mjs`) remains the thing that actually gates.

## After a run

Every reviewer run logs a `review`-type event (`provider`, `status`, `groundedCount`, `totalCitations`):

```
node .harness/scripts/ops/events.mjs --summarize --events
```

## Related

- `.harness/scripts/ops/review.mjs` — the runner this skill drives (`runReview` is the pure-ish
  exported core; `weightReview`/`extractCitations`/`gatherDiff` are the testable helpers; `main` is the
  thin CLI).
- `.harness/scripts/ops/events.mjs` — the event log every provider run writes to.
- [[deploy]] — the sibling ops runner this mirrors (config-driven, honest-abstain, injectable spawn).
- [[retro]] — reads the same event log; a good place to review cross-review history.
- [[decide]] — if you act against a cross-review's finding, log that call per `AGENTS.md`'s
  "overrides are audited, never silent" invariant.
