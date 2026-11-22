#!/usr/bin/env node
/**
 * @description `scaffold.mjs <incident|audit> "<title>"` — the scaffolder commands. Consumes the
 * guard-session (`requireGuard`, so `incident:new`/`audit:finding` are actually gated) and writes a
 * learning-loop-compliant note template into the config-declared errors/audits dir. Same `✓`/`✗`/`!`
 * console convention as doctor.mjs / guard.mjs.
 */
import { mkdirSync, existsSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadConfig } from './lib/config.mjs';
import { repoRoot as gitRoot } from './lib/repo.mjs';
import { requireGuard } from './lib/guard-session.mjs';
import { noteFilename, renderNote, targetDir } from './lib/scaffold-note.mjs';

/** note-kind → the guarded command name checked against `config.guard.scaffolderCommands`. */
const KIND_COMMAND = { incident: 'incident:new', audit: 'audit:finding' };

export function main(argv) {
  const kind = argv[0];
  const title = argv.slice(1).join(' ').trim();
  if (!KIND_COMMAND[kind] || !title) {
    console.error('usage: scaffold.mjs <incident|audit> "<title>"');
    return 2;
  }

  const root = gitRoot();
  const config = loadConfig(root);

  // The guard gates the attempt — no live session ⇒ fail closed with the guard's own message.
  const guard = requireGuard(root, config, KIND_COMMAND[kind]);
  if (!guard.ok) {
    console.error(`✗ ${guard.reason}`);
    return 1;
  }

  const dir = path.join(root, targetDir(kind, config));
  const file = path.join(dir, noteFilename(kind, title));
  const rel = path.relative(root, file).split(path.sep).join('/');
  if (existsSync(file)) {
    console.error(`✗ note already exists: ${rel} (refusing to overwrite)`);
    return 1;
  }

  mkdirSync(dir, { recursive: true });
  writeFileSync(file, renderNote(kind, title, config));

  console.log(`✓ scaffolded ${kind}: ${rel}`);
  console.log('! this note carries TODO: links that FAIL the learning-loop gate on purpose —');
  console.log('  it will BLOCK every commit until you replace them with a concrete path:line (or delete the note).');
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}
