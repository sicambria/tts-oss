---
name: deploy
description: Self-verified deploy — runs the full verify contract, deploys, healthchecks, logs every step to the observability spine, and rolls back automatically on a failed healthcheck. Config-driven via config.deploy; abstains (never silent-passes) if no deploy command is configured.
triggers:
  - "/deploy"
  - "deploy this"
  - "run the deploy"
  - "ship to prod"
  - "deploy and healthcheck"
---

# deploy

A named, repeatable, **self-verified** deploy: verify → (opt-in encrypted backup) → deploy →
healthcheck → log → rollback-on-failure, driven entirely by `config.deploy` in
`.harness/config.json`. This is the mechanism behind roadmap item P1-13 — the harness will not
deploy on top of a red verify contract, will not silently report success if there is nothing
configured to run, and automatically rolls back a deploy whose healthcheck fails.

Exists because ad-hoc deploys skip the two steps that catch most bad releases: confirming the
tree is actually green first, and confirming the deployed service is actually healthy after.
Both are cheap to skip under time pressure — this skill makes them the default path instead of
an afterthought.

## When to invoke

- The user asks to deploy, ship, or release the current tree.
- A CI/CD job wants a single, fail-closed deploy entrypoint instead of hand-rolled steps.

Do **not** invoke to deploy uncommitted or unverified work directly — the mechanism itself runs
`verify --phase full` first and aborts on red, so there is no need to pre-check, but do make sure
`config.deploy.cmd` is actually pointed at the right target before running it against production.

## Mechanism

```
node .harness/scripts/ops/deploy.mjs
```

Reads `config.deploy` from `.harness/config.json`:

```jsonc
"deploy": {
  "cmd": "",              // REQUIRED for this skill to do anything — the actual deploy command
  "healthcheckUrl": "",   // optional — HTTP GET, must return 2xx
  "healthcheckCmd": "",   // optional — spawned, must exit 0 (used if healthcheckUrl is unset)
  "rollbackCmd": "",      // optional — spawned automatically if the healthcheck fails
  "backupCmd": ""         // optional — run before deploy; see encrypted backup below
}
```

**Honest-abstain:** if `config.deploy.cmd` is empty, the runner logs an `abstain` event and exits
non-zero with a clear message — it never reports success by doing nothing. Fill `config.deploy.cmd`
to enable it.

**Steps** (each logged as a `deploy` event via `.harness/scripts/ops/events.mjs`, so `/retro` and
the dashboard see every run):

1. **Verify** — `node .harness/scripts/verify.mjs --phase full`. Red → abort before touching `cmd`.
2. **Backup (opt-in)** — if `backupCmd` is set, it runs before the deploy. Point it at writing its
   artifact into `.harness/state/backups/`; if the `KZ_DEPLOY_BACKUP_KEY` environment variable is
   also set, the most-recently-modified file in that directory is encrypted with AES-256-GCM
   (`node:crypto`, no new dependency) and the plaintext is deleted. No `backupCmd` → step is
   skipped, not failed.

   **Restoring an encrypted backup** — the harness only encrypts; it does not ship an automated
   restore path. The on-disk format of `<file>.enc` is `iv(12 bytes) || authTag(16 bytes) ||
   ciphertext`, keyed by `SHA-256(KZ_DEPLOY_BACKUP_KEY)`. Decrypt with a one-off Node script:
   ```js
   import { createHash, createDecipheriv } from 'node:crypto';
   import { readFileSync, writeFileSync } from 'node:fs';
   const raw = readFileSync('backup.sql.enc');
   const key = createHash('sha256').update(process.env.KZ_DEPLOY_BACKUP_KEY).digest();
   const decipher = createDecipheriv('aes-256-gcm', key, raw.subarray(0, 12));
   decipher.setAuthTag(raw.subarray(12, 28));
   writeFileSync('backup.sql', Buffer.concat([decipher.update(raw.subarray(28)), decipher.final()]));
   ```
3. **Deploy** — spawns `cmd`. Non-zero exit → logged and aborted; no healthcheck/rollback is
   attempted (a deploy binary that itself failed has nothing running to roll back from).
4. **Healthcheck** — `healthcheckUrl` (HTTP GET, must be 2xx) or `healthcheckCmd` (must exit 0).
   Neither configured → skipped (optional, same as `verify`'s `e2e`/`healthcheck` fields).
5. **Rollback-on-failure** — a failed healthcheck runs `rollbackCmd` (if configured) and always
   reports the deploy as **failed**, regardless of whether the rollback itself succeeded.

## After a run

Check what happened without re-reading logs by eye:

```
node .harness/scripts/ops/events.mjs --summarize --events
```

Every `deploy`-type event carries a `step` (`verify`/`backup`/`deploy`/`healthcheck`/`rollback`)
and a `status` (`start`/`ok`/`fail`/`abstain`/`skipped`) — enough to reconstruct exactly where a
run stopped.

## Related

- `.harness/scripts/ops/deploy.mjs` — the runner this skill drives (`runDeploy` is the pure-ish
  exported core; `main` is the thin CLI).
- `.harness/scripts/verify.mjs` — the verify contract this always runs first.
- `.harness/scripts/ops/events.mjs` — the event log every step writes to.
- [[retro]] — reads the same event log; a good place to review a deploy history.
- [[decide]] — if a deploy is manually overridden (e.g. skipping a failed healthcheck's rollback),
  log that override here per `AGENTS.md`'s "overrides are audited, never silent" invariant.
