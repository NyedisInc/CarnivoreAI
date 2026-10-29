import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const macDir = path.join(root, 'macOS');
const SKIP_DIRS = new Set(['node_modules', 'dist', 'out', '.git']);

const LEGACY = new Set([
  'bootstrap.js', 'engine/fs-perms.js', 'launchagent-installer.js', 'log-rotation.js', 'payload/sign-payload.sh',
  'scripts/adhoc-sign.js', 'scripts/release-build.sh', 'scripts/signing-config.js', 'scripts/signing-keychain-session.sh', 'scripts/signing-keychain.js',
  'scripts/vm-rig/vm-readout.sh', 'terminal-launcher.js', 'userdata-migration.js',
]);

export function shellFiles(dir = macDir, rel = '') {
  const out = [];
  for (const e of fs.readdirSync(path.join(dir, rel), { withFileTypes: true })) {
    const r = rel ? `${rel}/${e.name}` : e.name;
    if (e.isDirectory()) { if (!SKIP_DIRS.has(e.name)) out.push(...shellFiles(dir, r)); }
    else if (/\.(js|cjs|mjs|sh)$/.test(e.name)) out.push(r);
  }
  return out;
}

export function codeLines(text) {
  return text.split('\n').map((l, i) => [i + 1, l]).filter(([, l]) => !/^\s*(\/\/|\*|\/\*|#)/.test(l));
}

const LIBRARY = /Library\//;
const SECURITY = /\/usr\/bin\/security|(?:exec|spawn)\w*\(\s*['"]security['"]/;

export function pathAndSecretHits(file, text) {
  const hits = [];
  for (const [n, l] of codeLines(text)) {
    if (LIBRARY.test(l)) hits.push(`${file}:${n}: Library/ path literal (take paths from app.getPath)`);
    if (SECURITY.test(l)) hits.push(`${file}:${n}: calls security (secrets go through the engine, not the shell)`);
  }
  return hits;
}

export function dockHits(file, text) {
  const lines = codeLines(text);
  const raw = text.split('\n');
  const hits = [];
  for (const [n, l] of lines) {
    if (!/\bapp\.dock\b/.test(l)) continue;
    const window = raw.slice(Math.max(0, n - 5), n).join('\n');
    if (!/darwin/.test(window)) hits.push(`${file}:${n}: app.dock without a darwin guard (a Dock exists on macOS only)`);
  }
  return hits;
}

export function archHits(file, text) {
  return codeLines(text).filter(([, l]) => /\b(arm64|x64)\b/.test(l)).map(([n]) => `${file}:${n}: hard-coded architecture (read macOS/release-arch.json)`);
}

export function allHits() {
  const hits = [];
  for (const f of shellFiles()) {
    const text = fs.readFileSync(path.join(macDir, f), 'utf8');
    if (!LEGACY.has(f)) hits.push(...pathAndSecretHits(`macOS/${f}`, text));
    hits.push(...dockHits(`macOS/${f}`, text));
  }
  for (const f of ['macOS/scripts/publish-update-assets.sh']) {
    hits.push(...archHits(f, fs.readFileSync(path.join(root, f), 'utf8')));
  }
  const arch = JSON.parse(fs.readFileSync(path.join(macDir, 'release-arch.json'), 'utf8'));
  if (typeof arch.dmg_arch !== 'string' || !Array.isArray(arch.single_arch_name_tokens)) hits.push('macOS/release-arch.json: dmg_arch or single_arch_name_tokens missing');
  return hits;
}

assert.equal(pathAndSecretHits('x.js', "const p = home + '/Library/Logs/x';").length, 1);
assert.equal(pathAndSecretHits('x.js', "execFile('/usr/bin/security', ['find']);").length, 1);
assert.equal(pathAndSecretHits('x.js', "spawnSync('security', []);").length, 1);
assert.equal(pathAndSecretHits('x.js', '// ~/Library/Logs is where it was\nconst a = 1;').length, 0);
assert.equal(dockHits('x.js', 'app.dock.setBadge("1");').length, 1);
assert.equal(dockHits('x.js', "if (process.platform === 'darwin') {\n  app.dock.hide();\n}").length, 0);
assert.equal(archHits('x.py', 'name = f"Carnivore-{v}-arm64.dmg"').length, 1);
assert.equal(archHits('x.py', '# arm64 only in a comment').length, 0);

assert.ok(shellFiles().length > 50, 'the scan found the shell files');
const hits = allHits();
assert.deepEqual(hits, [], `port seam violations:\n${hits.join('\n')}`);
console.log('ok test_port_seams');
