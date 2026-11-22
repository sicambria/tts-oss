---
name: migration-check
description: Pre-flight checklist for a migration or large move using read-only inspection. Pass the migration target area, e.g. a directory or module name.
argument-hint: "<target-area>"
context: fork
agent: Explore
allowed-tools: Bash(git *), Bash(gh *), Bash(rg *)
---

# Migration pre-flight check

Target area: $ARGUMENTS. If empty, stop and ask for the target area — do not guess.

## Current state of the target

!`git status --short -- $ARGUMENTS`

## Recent history touching the target

!`git log --oneline -15 -- $ARGUMENTS`

## Open pull requests touching the target

!`gh pr list --state open --limit 20 --json number,title --jq '.[] | "#\(.number) \(.title)"'`

Report, from the substituted read-only output only: uncommitted work in the target, active
parallel efforts (open PRs, recent authors), and anything that must land or be shelved before
the migration starts. Propose an ordering, but change nothing.
