---
name: retro
description: Synthesize a retro from the observability event log (.harness/state/events.jsonl) — writes a dated retro under .harness/archive/retros/ summarizing decisions, gate overrides, and other logged events since the last retro.
triggers:
  - "/retro"
  - "run a retro"
  - "synthesize a retro"
  - "what happened this session"
---

# retro

A named, repeatable close-out: read the observability event log and synthesize a **retro** —
what happened (decisions logged, events by type), what stands out, and what should change —
into a dated file under `.harness/archive/retros/`. This is the read side of the observability
spine that `[[decide]]` writes into.

Exists because decisions and events accumulate silently in `.harness/state/events.jsonl`
(runtime, gitignored) unless something periodically turns them into a human-facing,
**committed** artifact. A retro is that artifact — the loop-closing step, same spirit as the
postmortem `INDEX.md` for incidents.

## When to invoke

- End of a work session, wave, or sprint — before the user moves on, to capture what happened
  while it's cheap to reconstruct.
- The user explicitly asks for a retro / "what happened" summary.
- After an `agent-protocol` wave finishes (complements, doesn't replace, that skill's own
  retro-of-retros phase — this one is event-log-grounded, not agent-self-reported).

Do **not** invoke if `.harness/state/events.jsonl` has no new events since the last retro —
say so plainly rather than manufacturing content.

## Steps

1. **Pull the summary.** Run:

   ```
   node .harness/scripts/ops/events.mjs --summarize --events
   ```

   This prints `{ total, byType, firstTs, lastTs, events }` — the full event list plus counts,
   so you can synthesize without hand-parsing the JSONL.

2. **(Optional) refresh the dashboard** for a visual cross-check:

   ```
   node .harness/scripts/ops/materialize.mjs
   ```

   writes `.harness/state/dashboard.html` (self-contained, open in a browser).

3. **Synthesize**, don't just dump. Read the `decision`-type events (and their linked files
   under `.harness/archive/decisions/`) plus any other event types present, and write a retro
   covering: what got done, notable decisions/overrides and why, anything that recurred or
   surprised, and concrete follow-ups (route them to a plan or `.harness/archive/decisions/` if
   they're their own decision).

4. **Write the file.** `.harness/archive/retros/<YYYY-MM-DD>-<kebab-slug>.md` (exempt/committed
   the same way decisions are — `^\.harness/archive/` in `.harness/config.json`). Suggested
   shape:

   ```markdown
   # Retro: <slug>

   **Date:** <YYYY-MM-DD>
   **Window:** <firstTs> → <lastTs> (<total> events)

   ## What happened
   <narrative, grounded in the event list>

   ## Decisions logged
   - <link to each .harness/archive/decisions/*.md touched this window>

   ## Notable / recurring
   <anything worth flagging>

   ## Follow-ups
   - <concrete next action, or "none">
   ```

5. **Log the retro itself** as an event (closes the loop — the dashboard's "Retro links"
   section reads this):

   ```
   node .harness/scripts/ops/events.mjs --type retro \
     --file .harness/archive/retros/<filename>.md
   ```

## Related

- [[decide]] — the write side; this skill reads what it logs.
- `.harness/scripts/ops/events.mjs` — `readEvents`/`summarize`/CLI `--summarize`.
- `.harness/scripts/ops/materialize.mjs` — `renderDashboard`, the visual counterpart.
- `.harness/archive/postmortems/INDEX.md` — the sibling closed-loop artifact for incidents
  (different mechanism, same "close the loop with a real artifact" spirit).
