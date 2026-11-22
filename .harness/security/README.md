# Secret governance (`.harness/security/`)

Portable secret-scan governance for the kaizen `secret-scan` gate
(`.harness/gates/core.gates.json` → `verify-secrets.mjs --staged`).

## Two scanner tiers

`security.secretScanner` in `.harness/config.json` selects the tier:

| value      | behaviour                                                                             |
|------------|---------------------------------------------------------------------------------------|
| `gitleaks` | Run gitleaks. If configured but not installed, the gate **fails closed** (never skips).|
| `none`     | Run the **pure-Node fallback scanner** — dependency-free, always enforcing.             |

`kaizen init` sets `gitleaks` when the binary is present, else `none`. Either way the gate enforces;
`none` is no longer a silent skip.

## Pure-Node fallback ruleset

Regex + entropy rules (see `RULES` in `verify-secrets.mjs`): AWS access-key IDs (`AKIA…`), PEM
private-key headers, GitHub personal/OAuth/app tokens, Slack tokens, keyword-anchored
`api_key=`/`secret=`/`token=` assignments, and high-entropy base64 blobs. The two false-positive-prone
rules (generic assignment, high-entropy base64) are gated by a Shannon-entropy threshold.

Scan modes:

```
node .harness/scripts/audits/verify-secrets.mjs --staged   # added lines of the staged diff (the gate)
node .harness/scripts/audits/verify-secrets.mjs FILE …      # scan specific files
node .harness/scripts/audits/verify-secrets.mjs             # detect: every git-tracked text file
```

Exit code is non-zero when an unsuppressed finding (or an expired allowlist entry) is present.

## Suppressing a finding

Every finding has a stable **fingerprint** — `sha256(rule + value)`, independent of file path and line
number, so it survives code moving around. The scanner prints it: `… fingerprint=<sha256-hex>`.

Two suppression stores:

- **`.secrets.baseline`** — permanent. JSON: add the fingerprint as a key under `secrets`:
  ```json
  { "version": 1, "secrets": { "<sha256-hex>": { "reason": "…" } } }
  ```
- **`allowlist.yaml`** — temporary, with a **mandatory `expires:` date**. An unexpired entry suppresses
  the fingerprint; an **expired entry fails the gate**, forcing rotation. See the header of that file.

A malformed baseline or allowlist entry **fails closed** — it never silently suppresses.

## CI dependency scanning

`.github/workflows/osv-scan.yml` runs Google OSV-Scanner (pinned) on push, PR, and weekly, flagging
known-vulnerable dependencies. It is independent of the local secret-scan gate.
