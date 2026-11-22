---
name: decide
description: Log an auditable decision — writes a dated decision record under .harness/archive/decisions/ and appends a `decision` event to the observability log. The mechanism behind AGENTS.md's "Overrides are audited, never silent" invariant and the general "why did we do X" record for any non-obvious call.
triggers:
  - "/decide"
  - "log a decision"
  - "record this decision"
  - "log an override"
  - "why did we decide"
---

# decide

A named, repeatable way to make a decision **auditable**: write a dated record under
`.harness/archive/decisions/` and log a `decision` event to the observability spine
(`.harness/scripts/ops/events.mjs`). This is the concrete mechanism behind `AGENTS.md`'s
"Overrides are audited, never silent" invariant — any gate override, scope cut, or non-obvious
architectural call gets a trace here, not just a Slack message or a commit-message aside.

Exists because "we decided X" without a record silently rots: the next session (or the next
agent) can't tell whether X was deliberate or accidental, and a gate override with no paper
trail is exactly the failure `AGENTS.md` calls out as forbidden.

## When to invoke

- A gate/guardrail override is being made (the audited-escape-hatch invariant makes this
  **mandatory**, not optional).
- A non-obvious scope cut, deferral, or architectural choice is made mid-task and future
  sessions will need to know it was intentional (e.g. "deferred X because Y" entries like the
  ones in `docs/plans/done/port-workflows-guardrails.md`'s disposition tables).
- The user explicitly asks to "log a decision" / "record this."

Do **not** invoke for routine implementation choices that don't need a standing record — this
is for decisions worth finding again later, not a running commentary.

## Steps

1. **Compose the record.** Gather: a one-line summary, the context/problem, options considered
   (if any), the chosen option, and the rationale. If this is a gate override, name the
   overridden gate and cite the concrete guardrail path being bypassed.
2. **Write the file.** `.harness/archive/decisions/<YYYY-MM-DD>-<kebab-slug>.md` (this dir is
   `branchGuard.exemptPaths`-exempt — `^\.harness/archive/` in `.harness/config.json` — so it
   commits directly on the default branch per `AGENTS.md` invariant #6a). Suggested shape:

   ```markdown
   # <Title>

   **Date:** <YYYY-MM-DD>
   **Context:** <what prompted this>

   ## Options considered
   - <option> — <why not>

   ## Decision
   <the chosen option, stated plainly>

   ## Rationale
   <why>

   ## Related
   <path:line citations, plan links, overridden gate name if applicable>
   ```

3. **Log the event.** Append a `decision` event so the dashboard and `/retro` can see it:

   ```
   node .harness/scripts/ops/events.mjs --type decision \
     --summary "<one-line summary>" \
     --file .harness/archive/decisions/<filename>.md
   ```

   (`events.mjs` never throws on a bad write — if it fails, still keep the markdown record; the
   record is the source of truth, the event is an index over it.)

4. **Confirm** the file path and event back to the user in one line.

## Related

- `AGENTS.md` — "Overrides are audited, never silent" (the invariant this closes).
- `.harness/scripts/ops/events.mjs` — `logEvent`/CLI this skill shells out to.
- `.harness/scripts/ops/materialize.mjs` — renders logged decisions into `dashboard.html`.
- [[retro]] — reads the same event log to synthesize periodic retros.
