---
name: review
description: Structured change review using read-only diff and check output. Pass a PR number, branch name, or leave blank for the working tree.
argument-hint: "[<pr-number-or-branch>]"
context: fork
agent: Explore
allowed-tools: Bash(git *), Bash(gh *)
---

# Change review

Target: $ARGUMENTS. If empty, review the uncommitted working tree.

## Diff under review

!`git diff --stat; git status --short`

## Check status

!`gh pr checks 2>/dev/null || echo "no PR checks available for this target"`

Review the substituted read-only output for: scope discipline (does the diff solve one
problem?), reuse (does an existing helper already cover this?), and subtraction candidates
(what can be deleted without losing the fix?). Report findings ranked must-fix vs polish.
Quality lens only — correctness hunting belongs to a dedicated bug review. Change nothing.
