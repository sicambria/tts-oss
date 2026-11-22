---
name: pr-summary
description: Summarize the current pull request using read-only GitHub CLI substitutions.
context: fork
agent: Explore
allowed-tools: Bash(gh *)
---

# Pull request summary

## Metadata

!`gh pr view --json number,title,url,author --jq '"#\(.number) — \(.title)\n\(.url)\nAuthor: \(.author.login)"'`

## Changed files

!`gh pr diff --name-only`

## Checks

!`gh pr checks`

Summarize the purpose, changed surface, and check status from the substituted read-only output. If no
pull request is open for the current branch, say so without attempting a write operation.
