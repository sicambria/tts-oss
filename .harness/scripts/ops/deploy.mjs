#!/usr/bin/env node
/**
 * @description Self-verified `/deploy` (P1-13, src: changemappers). A config-driven deploy runner:
 * verify → (opt-in encrypted backup) → deploy → healthcheck → log event → rollback-on-failure.
 * Reads `config.deploy` (`{ cmd, healthcheckUrl, healthcheckCmd, rollbackCmd, backupCmd }`, all
 * optional strings). Honest-abstain per the harness's fail-closed philosophy
 * (`.harness/scripts/verify.mjs`'s `human_needed` shape): an empty/missing `config.deploy.cmd`
 * ABSTAINS (exit 1, an error printed, an `abstain` event logged) — it never silently "succeeds" by
 * doing nothing.
 *
 * Steps, each logged via `.harness/scripts/ops/events.mjs`'s `logEvent` so `/retro` and the
 * dashboard see every deploy:
 *   1. abstain-check   — cmd empty → log + exit 1, nothing else runs.
 *   2. verify           — `node .harness/scripts/verify.mjs --phase full`. Red → abort before
 *                          touching `cmd` (never deploy on top of a red verify contract).
 *   3. backup (opt-in)  — if `backupCmd` set, run it. If `KZ_DEPLOY_BACKUP_KEY` is also set, the
 *                          most-recently-modified file under `.harness/state/backups/` is encrypted
 *                          (AES-256-GCM via `node:crypto` — dependency-free, no new runtime dep) and
 *                          the plaintext is deleted. No `backupCmd` → step is skipped, not failed.
 *   4. deploy           — spawn `cmd`. Non-zero → log + exit 1. No healthcheck/rollback attempted:
 *                          a deploy binary that itself failed has nothing running to roll back from.
 *   5. healthcheck       — `healthcheckUrl` (HTTP GET via global `fetch`, Node 18+) or
 *                          `healthcheckCmd` (spawned, exit 0 required). Neither set → skipped
 *                          (optional, like verify.mjs's e2e/healthcheck fields).
 *   6. rollback-on-fail — healthcheck failure → if `rollbackCmd` set, spawn it (logged either way);
 *                          deploy is reported FAILED regardless of whether rollback itself succeeded.
 *
 * Pure-ish core `runDeploy(root, cfg, { spawn, fetchImpl })` — both collaborators are injectable so
 * the full state machine (including a failing healthcheck → rollback path) is unit-testable without
 * touching the network or a real process. Mirrors the injectable-collaborator DI seam already used by
 * `.harness/scripts/lib/guard-session.mjs` (commandExists) and the pure-core-plus-thin-CLI shape of
 * every other `ops/*.mjs` script (`events.mjs`, `materialize.mjs`, `statusline.mjs`).
 *
 * Usage: node deploy.mjs
 */
import { spawnSync } from 'node:child_process';
import { existsSync, readdirSync, statSync, readFileSync, writeFileSync, unlinkSync } from 'node:fs';
import { createCipheriv, createHash, randomBytes as cryptoRandomBytes } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from '../lib/config.mjs';
import { repoRoot as gitRoot } from '../lib/repo.mjs';
import { logEvent } from './events.mjs';

const BACKUPS_REL = path.join('.harness', 'state', 'backups');

/** Default `spawn` collaborator: runs a shell command string, inherits stdio, returns `{status}`. */
function defaultSpawn(command, opts = {}) {
  const r = spawnSync(command, { cwd: opts.cwd, stdio: opts.stdio ?? 'inherit', shell: true });
  return { status: r.status ?? (r.signal ? 1 : 0), stdout: r.stdout, stderr: r.stderr };
}

/** Default `fetchImpl` collaborator: global `fetch` (Node >=18, no new dep) or null if unavailable. */
function defaultFetch() {
  return typeof fetch === 'function' ? fetch : null;
}

/**
 * Absolute path to the most-recently-modified regular file directly under `.harness/state/backups/`,
 * excluding already-encrypted (`.enc`) files. Returns null if the dir is absent/empty. Pure fs read,
 * no process spawn — `backupCmd` is expected to write its artifact into this dir by convention.
 * @param {string} root repo root
 */
export function latestBackupFile(root) {
  const dir = path.join(root, BACKUPS_REL);
  if (!existsSync(dir)) return null;
  let entries;
  try {
    entries = readdirSync(dir);
  } catch {
    return null;
  }
  const files = entries
    .filter((f) => !f.endsWith('.enc'))
    .map((f) => path.join(dir, f))
    .filter((p) => {
      try {
        return statSync(p).isFile();
      } catch {
        return false;
      }
    })
    .map((p) => ({ p, mtime: statSync(p).mtimeMs }));
  if (!files.length) return null;
  files.sort((a, b) => b.mtime - a.mtime);
  return files[0].p;
}

/**
 * Encrypt `filePath` with AES-256-GCM, keyed by SHA-256(secret) (so any-length secret becomes a valid
 * 32-byte key — dependency-free, `node:crypto` only, mirrors the existing crypto-without-a-dep
 * precedent in `.harness/scripts/lib/guard-session.mjs`'s `randomBytes` use). Writes `<filePath>.enc`
 * as `iv(12) || authTag(16) || ciphertext`, deletes the plaintext, and returns the `.enc` path.
 * @param {string} filePath absolute path to the plaintext backup artifact
 * @param {string} secret the raw `KZ_DEPLOY_BACKUP_KEY` value
 */
export function encryptBackupFile(filePath, secret) {
  const key = createHash('sha256').update(String(secret)).digest();
  const iv = cryptoRandomBytes(12);
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const plaintext = readFileSync(filePath);
  const ciphertext = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const authTag = cipher.getAuthTag();
  const destPath = `${filePath}.enc`;
  writeFileSync(destPath, Buffer.concat([iv, authTag, ciphertext]));
  unlinkSync(filePath);
  return destPath;
}

/**
 * Run the self-verified deploy state machine. Never throws — every failure path returns a non-zero
 * exit code after logging an event. `spawn`/`fetchImpl` are injectable for tests.
 * @param {string} root repo root (absolute)
 * @param {object} cfg loaded harness config (`loadConfig(root)`)
 * @param {{spawn?: Function, fetchImpl?: Function}} [opts]
 * @returns {Promise<number>} process exit code
 */
export async function runDeploy(root, cfg, opts = {}) {
  const spawn = opts.spawn || defaultSpawn;
  const fetchImpl = opts.fetchImpl !== undefined ? opts.fetchImpl : defaultFetch();
  const d = (cfg && cfg.deploy) || {};
  const cmd = (d.cmd || '').trim();

  // 1. Abstain check — honest-abstain, never silent-pass.
  if (!cmd) {
    logEvent(root, { type: 'deploy', step: 'deploy', status: 'abstain', reason: 'config.deploy.cmd is empty' });
    console.error('✗ deploy: human_needed — config.deploy.cmd is empty. Fill config.deploy.cmd to enable /deploy.');
    return 1;
  }

  // 2. Verify (fail closed — abort before touching cmd).
  logEvent(root, { type: 'deploy', step: 'verify', status: 'start' });
  const verifyR = spawn('node .harness/scripts/verify.mjs --phase full', { cwd: root });
  if (verifyR.status !== 0) {
    logEvent(root, { type: 'deploy', step: 'verify', status: 'fail' });
    console.error('✗ deploy: verify --phase full failed — aborting before deploy.');
    return 1;
  }
  logEvent(root, { type: 'deploy', step: 'verify', status: 'ok' });

  // 3. Backup (opt-in; skipped, not failed, when unset).
  if ((d.backupCmd || '').trim()) {
    logEvent(root, { type: 'deploy', step: 'backup', status: 'start' });
    const backupR = spawn(d.backupCmd, { cwd: root });
    if (backupR.status !== 0) {
      logEvent(root, { type: 'deploy', step: 'backup', status: 'fail' });
      console.error('✗ deploy: backupCmd failed — aborting before deploy.');
      return 1;
    }
    let note = 'backup complete (not encrypted — set KZ_DEPLOY_BACKUP_KEY to enable)';
    const secret = process.env.KZ_DEPLOY_BACKUP_KEY;
    if (secret) {
      const latest = latestBackupFile(root);
      if (latest) {
        const encPath = encryptBackupFile(latest, secret);
        note = `encrypted: ${path.relative(root, encPath)}`;
      } else {
        note = 'backupCmd ran but produced no file under .harness/state/backups/ — nothing to encrypt';
      }
    }
    logEvent(root, { type: 'deploy', step: 'backup', status: 'ok', note });
  }

  // 4. Deploy.
  logEvent(root, { type: 'deploy', step: 'deploy', status: 'start' });
  const deployR = spawn(cmd, { cwd: root });
  if (deployR.status !== 0) {
    logEvent(root, { type: 'deploy', step: 'deploy', status: 'fail' });
    console.error(`✗ deploy: cmd failed (exit ${deployR.status ?? 'signal'})`);
    return 1;
  }
  logEvent(root, { type: 'deploy', step: 'deploy', status: 'ok' });

  // 5. Healthcheck (optional).
  const healthcheckUrl = (d.healthcheckUrl || '').trim();
  const healthcheckCmd = (d.healthcheckCmd || '').trim();
  let healthy = true;
  if (healthcheckUrl) {
    logEvent(root, { type: 'deploy', step: 'healthcheck', status: 'start', target: healthcheckUrl });
    healthy = false;
    if (fetchImpl) {
      try {
        const res = await fetchImpl(healthcheckUrl);
        healthy = !!(res && res.ok);
      } catch {
        healthy = false;
      }
    }
  } else if (healthcheckCmd) {
    logEvent(root, { type: 'deploy', step: 'healthcheck', status: 'start', target: healthcheckCmd });
    const hcR = spawn(healthcheckCmd, { cwd: root });
    healthy = hcR.status === 0;
  } else {
    logEvent(root, { type: 'deploy', step: 'healthcheck', status: 'skipped' });
  }

  if ((healthcheckUrl || healthcheckCmd) && !healthy) {
    logEvent(root, { type: 'deploy', step: 'healthcheck', status: 'fail' });
    console.error('✗ deploy: healthcheck failed.');
    // 6. Rollback-on-failure.
    const rollbackCmd = (d.rollbackCmd || '').trim();
    if (rollbackCmd) {
      logEvent(root, { type: 'deploy', step: 'rollback', status: 'start' });
      const rbR = spawn(rollbackCmd, { cwd: root });
      logEvent(root, { type: 'deploy', step: 'rollback', status: rbR.status === 0 ? 'ok' : 'fail' });
      if (rbR.status !== 0) console.error('✗ deploy: rollbackCmd also failed — manual intervention needed.');
      else console.error('  → rollback complete.');
    } else {
      console.error('  → no config.deploy.rollbackCmd configured — manual rollback needed.');
    }
    // A failed healthcheck is always a failed deploy, regardless of rollback outcome.
    return 1;
  }

  if (healthcheckUrl || healthcheckCmd) logEvent(root, { type: 'deploy', step: 'healthcheck', status: 'ok' });
  console.log('✓ deploy: complete.');
  return 0;
}

/** CLI entrypoint: `node deploy.mjs`. */
export async function main() {
  const root = gitRoot();
  const cfg = loadConfig(root);
  return runDeploy(root, cfg);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().then((code) => process.exit(code));
}
