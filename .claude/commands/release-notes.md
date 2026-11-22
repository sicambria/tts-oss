---
name: release-notes
description: Draft release notes from merged pull requests and tags using read-only git and gh substitutions. Pass a tag range or leave blank for the latest tag.
argument-hint: "[<from-tag>..<to-tag>]"
context: fork
agent: Explore
allowed-tools: Bash(git *), Bash(gh *)
---

# Release notes

Arguments: $ARGUMENTS. If empty, derive the range from the two most recent tags via the
substitution below instead of asking.

## Range

!`git describe --tags --abbrev=0 2>/dev/null; git describe --tags --abbrev=0 HEAD~1 2>/dev/null`

## Merged pull requests in range

!`gh pr list --state merged --limit 50 --json number,title,author,mergedAt --jq '.[] | "#\(.number) \(.title) (@\(.author.login), \(.mergedAt))"'`

## Commits since previous tag

!`git log --oneline -30`

Draft release notes grouped as Features / Fixes / Other from the substituted read-only output.
Never create the release or push tags — output markdown only. If no tags exist, say so and
summarize the recent commits instead.
