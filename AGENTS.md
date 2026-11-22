# AGENTS.md

Canonical instructions for AI coding agents in this repo. Read this first, then the files it points to.

## Orientation (read in this order)

1. `README.md` — what the app is and how users run it.
2. `run.sh` / `run.ps1`, `setup.sh` / `setup.ps1` — the real entrypoints. Read them before answering how to run/install.
3. `app.py` — the entire app (~6900 lines, single file, no module split).
4. `KNOWN_ISSUES.md` — confirmed behavior, environment pitfalls, past misdiagnoses. Check before changing setup/runtime.
5. `ANTIPATTERNS.md` — mandatory code-review checklist. Check during planning and before committing.
6. `AI_DEVELOPMENT_NOTES.md` — handoff notes for AI contributors.

## What this repo is

- Native `tkinter` desktop GUI (`Tk()` in `app.py`). **No browser UI, no localhost server, no HTTP endpoint. Never suggest one.**
- Launch: `./run.sh` (Linux/macOS), `.\run.ps1` (Windows). Setup: `./setup.sh [cpu|cu121]`, `.\setup.ps1 [-TorchChannel cu121]`.
- Engines: `Auto` (default) / `Piper` / `XTTS v2` / `Pocket TTS`. XTTS model: `tts_models/multilingual/multi-dataset/xtts_v2`.
- Everything lives in `app.py`: `SynthesisCoordinator`, `PiperService`, `XTTSService`, `PocketTTSService`, `AudioPlayer` (pygame), `App` (Tk root), `PiperVoiceWizard`, `DocumentToAudioWizard`, `DubbingWizard`, `LanguageLearningWizard`.
- Tests: `tests/` (pytest). Hooks: `.githooks/pre-commit` (ruff + pytest cov≥50), `.githooks/pre-push` (ruff + pytest cov≥85). Coverage exclusions in `pyproject.toml`.

## Commands

```bash
./run.sh                          # run GUI (Linux/macOS)
./setup.sh                        # CPU setup
./setup.sh cu121                  # CUDA 12.1
.venv/bin/python -m pytest        # full suite (must pass before push)
.venv/bin/python -m pytest tests/test_text_chunking.py  # focused example
.venv/bin/ruff check app.py tests/  # lint (must pass)
git diff --check                  # whitespace check
rg <pattern>                      # search (never grep .venv manually)
```

## Architecture rules (do not violate)

- **Language-first UI.** User picks Language → Engine dropdown filters via `engines_supporting_language()` → voice control adapts. Never reintroduce engine-first flow.
- **Capability registry is single source of truth:** `LANGUAGE_NAMES`, `XTTS_LANGUAGES`, `POCKET_LANGUAGES`, `POCKET_PREDEFINED_VOICES`, `ENGINE_SUMMARIES`. Piper coverage is **derived at runtime** via `piper_languages()` / `piper_language_of_code()` — never hardcode a Piper language list.
- **Engine resolution is unified** in `select_engine(engine, language, has_wav, piper_options)`. `Auto` is language-aware (won't pick Piper with no installed voice for that language). `SynthesisCoordinator.resolve_engine`, `App.resolved_engine`, wizard handlers all route through it. When handling engine change in a wizard, resolve `Auto` **before** setting field state (past bug: `61b9db8`).
- **Voice identity by code, not label.** Piper code e.g. `hu_HU-anna-medium`; Pocket voice from `POCKET_PREDEFINED_VOICES` dropdown (validated, friendly `RuntimeError`). Labels are UI-only.
- **Chunking contract** (`chunk_text_with_offsets` → `TextChunk(text, start, end)`): sentence/paragraph-boundary-first, clause fallback, word fallback; chunks are non-overlapping monotonic `source[start:end].strip()` slices; whitespace gaps only. Never replace with word-only splitting for highlighting (caused XTTS duplicate-word RCA, `cf86955`, `plans/2026-08_RCA_xtts-duplicate-audio.md`). Keep XTTS `split_sentences=True`.
- **Threading:** all GUI updates from workers via `root.after(0, ...)`. **Never read Tk vars on a worker thread** — snapshot all UI state (page range, format, engine, voice, quality, speed) on the UI thread and pass an immutable snapshot to the worker (past bug: pages 61–70 synthesized full doc, `plans/2026-08_RCA_page-range-worker-snapshot.md`).
- **Trace guards:** voice/engine sync methods use `_syncing_*` flags; guard new widget access with `hasattr`/`getattr` so headless tests (partial widget mocks) don't break.
- **Empty-text early exit** before loading voice state in synthesis paths (past bug: `61b9db8`).
- **WAV cache:** `_voice_cache_path` returns `None` for WAV file paths — never cache reference-WAV voices as safetensors (past stale-cache bug: `61b9db8`).

## Never repeat these past errors

1. **No web server.** Confirm GUI type from code (`Tk()`), not assumption. Past agents repeatedly suggested `localhost`/browser URLs.
2. **Search discipline.** Use `rg` from root; `.rgignore` excludes `.venv/`, `output/`, `__pycache__/`, `voices/`. Never infer project structure from `.venv`.
3. **Tk/Xft font issue (the big one).** Boxed icons + boxed `ő`/`ű` + "can't type accents" are ONE root cause: uv's standalone Python bundles Tk **without Xft** (~58 core bitmap fonts, everything falls back to `fixed`). Fix is interpreter choice (pyenv/system Python 3.11 with `tk-dev`, `setup.sh` auto-prefers it, `TTS_PYTHON=` override), never font-name changes. Verify with font probe (`len(font.families())` in hundreds), not "process started, exit 0". Do NOT add `XMODIFIERS`/IME fixes — that was a phantom second diagnosis (`5a06722`, `dcacc6e`, `debc61a`, `KNOWN_ISSUES.md`).
4. **Non-ASCII voice URLs.** Percent-encode with `quote()` using the catalog `files` dict; `urlopen` raises `UnicodeEncodeError` on e.g. `pt_PT-tugão-medium` otherwise (`04dd8b1`).
5. **Piper speed API.** Use `SynthesisConfig`, not bare `length_scale` kwarg (`b85dfcd`).
6. **Missing imports break features.** `DoubleVar` was forgotten for the speed slider (`b81f64a`). After adding widgets, run focused tests + full suite.
7. **Hook venv paths.** Hooks must use `$SCRIPT_DIR/.venv/bin/...`, broke once (`315769d`). Pre-push gate is cov≥85 — add tests with features.
8. **numpy pin.** Keep `numpy==1.26.4`: Pocket TTS 2.1.0 wants `numpy>=2`, `gruut` (Piper) wants `numpy<2.0.0`. 1.26.4 satisfies both at runtime; pip warning is expected and ignored.
9. **Linux system deps.** `python3-tk` + SDL audio libs are outside pip. Document new machine deps in `README.md`, pitfalls in `KNOWN_ISSUES.md`.
10. **Don't commit generated noise.** `settings.json` / `settings.json.bak` churn polluted history — they are git-ignored; don't force-add them.

## Session-start invariants (violation = blocker)

1. **Before ANY edit:** run `git branch --show-current` and `git status --short`. Know whether you are on `main` and whether the tree is dirty.
2. **Keep `main` clean.** Substantive multi-step (non-docs) work goes on a branch/worktree first, then merges when clean and green. Only docs/config (`*.md`, settings templates, hooks config) may commit directly to `main`.
3. **After context compaction:** re-read this file and the active plan before continuing.
4. **After ANY `git push`:** verify with `git rev-list --left-right --count origin/<branch>...<branch>`. AHEAD must be 0. If the command timed out, the push did NOT complete — re-verify.

## Verify and gates (never bypass)

- The gates are the product: `.githooks/pre-commit` (ruff + pytest cov≥50), `.githooks/pre-push` (ruff + pytest cov≥85). **Never use `--no-verify`, never bypass hooks.** A bypass that reaches `main` is a defect.
- If a gate is wrong, fix the gate (and log the decision in the commit message and/or `KNOWN_ISSUES.md`) — don't skip it. Any override must leave a trace; a silent override is forbidden.

## Plan before code and learning loop

- Non-trivial work gets a plan file under `plans/` before implementation (follow the existing `YYYY-MM_*` naming and RCA format). Reference it while implementing.
- On any real bug: check `KNOWN_ISSUES.md` and `plans/` RCAs first, do RCA, then close the loop with a real prevention artifact — a regression test plus a `KNOWN_ISSUES.md` / `ANTIPATTERNS.md` update. Never a prose-only fix.

## Before committing

- Always commit when the task is done. Do not leave changes uncommitted in the working tree.
- Run: `ruff check`, full `pytest`, `git diff --check`. Pre-push requires coverage ≥85%.
- Walk the `ANTIPATTERNS.md` checklist: no `sys.path.insert` hacks, numeric `Entry` validation, config-corruption warning+backup, temp-file tracking (no fixed-delay `after` unlink), specific exceptions in workers, cache hot paths, labels match behavior, context menus on all `Entry`/`Text`, normalized (NFD+strip+lower) user-input matching, dependency health check at feature entry.
- Keep Python floor `>=3.9,<3.12` (Coqui wheels). `pyproject.toml`: ruff line-length 120, `E402/E501` ignored.
- Docs: new machine dependency → `README.md`; recurring pitfall → `KNOWN_ISSUES.md`.

<!-- BEGIN kaizen (managed — do not edit inside this block) -->
# Agent Operating Contract (kaizen harness)

> Canonical, tool-agnostic driver. Per-agent files (`CLAUDE.md`, `.cursor/rules`, `.codex`,
> `opencode.jsonc`, `.github/copilot-instructions.md`) are thin overlays that import this file.
> This is the source of truth — edit here, then regenerate overlays (`kaizen init --check` detects drift).

## Session-start invariants (violation = blocker)
1. **Before ANY edit:** run `git branch --show-current` and `git worktree list --porcelain`. If on the
   default branch (see `.harness/config.json` → `defaultBranch`) and the task changes any substantive
   (non-docs) file, **STOP and create a worktree first**, then merge at the end.
2. **Never leave the default branch with uncommitted substantive changes.** Substantive work goes in a
   worktree → merge to the default branch only when it is clean.
3. **After ANY `git push`:** verify with `git rev-list --left-right --count origin/<branch>...<branch>`.
   The AHEAD count MUST be 0. If the command timed out, the push did NOT complete — re-verify.
4. **After context compaction:** re-read this file and the active plan before continuing.
5. **Never use `--no-verify`.** The gates are the product. A bypass that reaches the default branch is a
   defect. If a gate is wrong, fix the gate (and log the decision), don't skip it.

## Plan-before-code (enforced)
- Non-trivial work gets a plan file under `.harness/plans/` before implementation.
- Every plan MUST contain a `## Standards & Guardrails Evidence` section whose `path:line` citations
  **resolve against the working tree** — a hallucinated citation hard-fails the commit
  (`.harness/scripts/audits/verify-plan-evidence.mjs`). Check off every configured evidence dimension
  with a resolving citation or an explicit `N/A — reason`.

## Verify contract
- The stack's real checks live behind `.harness/config.json → verify` (`test`/`lint`/`build`/`e2e`/`healthcheck`).
- `.harness/scripts/verify.mjs` runs them. A required check that cannot be mechanically confirmed
  **abstains (`human_needed`)** and fails closed — it never silently passes.

## SOTA scorecard (capability self-assessment)
- `node .harness/scripts/ops/sota-score.mjs` scores the harness **0–1000** against an embedded
  11-aspect weighted rubric, grading **function over presence** — a capability earns full credit only
  when `doctor` reports it wired-and-healthy, partial (0.5) when merely present, zero when absent.
  Flags: `--json`, `--write` (persists a snapshot to the event spine), `--min <n>` (opt-in gate).
  **Advisory / exit 0 by default** — a subjective score is deliberately never wired as a silent hard gate.
- It is a **capability-coverage** score (how much SOTA-harness capability is present and healthy here),
  **NOT** a benchmark-measured performance SOTA position — keep the two distinct.

## Install-time strengthening (never weaken existing controls)
- Installing kaizen must only ever *add* enforcement, never subtract it. `kaizen init` takes over
  `core.hooksPath`, so it **chains** the repo's pre-existing hooks (husky / pre-commit framework / hand-written
  `.git/hooks` / a custom hooksPath) — they keep firing and keep blocking, recorded in `config.hooks.chained`
  and run fail-closed by the drivers. A control that blocked a commit/push before install still blocks it after.
- An AI performing an install follows the same rule. If the target repo already has a good pattern the harness
  lacks, **strengthen the harness in place** (add it to `templates/` + the dogfood mirror, dual-tree) rather than
  leaving the adopter's enforcement weaker than you found it or shipping a one-off local hack. Never `--no-verify`,
  never silently orphan a gate; if a chained control is genuinely wrong, fix or retire it with a logged decision.

## Incident & learning loop (closed)
- On discovering any real bug: check `.harness/archive/postmortems/INDEX.md` first, do RCA, then scaffold
  an incident note (metadata + Summary/Root Cause/Prevention/Guardrail Updates/Automation Follow-Up).
- The note MUST cite a concrete guardrail path and automation path — the loop closes on a real prevention
  artifact, never prose. `verify-learning-loop.mjs` gates it and regenerates the index deterministically.

## Memory (survives context resets, committed in-repo)
- `.harness/memory/memory.md` is the hot, auto-loaded index. `project.md`/`user.md` are semantic;
  `episodic/` holds daily journals; `procedural/` holds distilled reusable skills. All committed in-repo.

## Behavioral contract & invariants (the layer beneath the gates)
- The tiered agent contract (T0 halt / T1 waiver / T2 best-effort / T3 graceful), the agent execution state
  machine, stop triggers, assumption budget, and Intent Gate live in `.harness/memory/rules.md`. Re-read its
  T0/T1 tiers + state machine at session start, after compaction, and at plan→execution transitions.
- `.harness/INVARIANTS.md` is the invariant registry + blast-radius Protection Matrix: when a change's blast
  radius intersects a threat category, consult the named invariant and apply the tier-appropriate response.
- Rationale (the MAST-grounded failure-mode taxonomy) is in `.harness/reference/failure-modes.md` — a design
  artifact, deliberately **not** hot-loaded, to keep the per-session context budget lean.

## Overrides are audited, never silent
- Any gate override must append a justified entry to `.harness/archive/decisions/` — an override that
  leaves no trace is forbidden.

## Session-start contract-read canary
Prove you actually ingested the contract (not just this pointer overlay): four **canary words** are
embedded as HTML-comment markers (format `CANARY: <word>`), one in each of `AGENTS.md`,
`.harness/memory/rules.md`, `.harness/INVARIANTS.md`, and `.harness/memory/memory.md`. **Surface all four
at session start.** Claude enforces contract-read through its SessionStart hook; for hook-less providers
(Cursor / Codex / opencode / Copilot) this canary is the read-compliance signal they otherwise lack. The
marker *integrity* (exactly one per file, all listed here) is gated by
`.harness/scripts/audits/verify-canary.mjs` — a marker that drifts out of sync fails closed.
<!--CANARY: MARBLE-->
<!-- END kaizen -->
