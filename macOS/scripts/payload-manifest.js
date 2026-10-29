'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');
const { TREE_ARCHES } = require('../engine/payload-select');
const { SIGNING_TEAM_ID } = require('./signing-config');

const PAYLOAD_DIR = path.join(__dirname, '..', 'payload');
const MANIFEST_NAME = 'payload-manifest.json';
const MACH_O_MAGIC = new Set(['cefaedfe', 'cffaedfe', 'feedface', 'feedfacf', 'cafebabe', 'bebafeca', 'cafebabf', 'bfbafeca']);

function lockWheels(lockText) {
  const rows = [];
  for (const line of lockText.split('\n')) {
    const pin = /^([A-Za-z0-9][A-Za-z0-9_.-]*)==([^\s;\\]+)/.exec(line);
    if (pin) {
      rows.push({ name: pin[1], version: pin[2], source: 'pypi', sha256: [] });
      continue;
    }
    const hash = /^\s+--hash=sha256:([0-9a-f]{64})/.exec(line);
    if (hash && rows.length > 0) rows[rows.length - 1].sha256.push(hash[1]);
  }
  return rows;
}

function machoHashes(treeDir) {
  const rows = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isSymbolicLink()) continue;
      if (entry.isDirectory()) { walk(full); continue; }
      if (!entry.isFile()) continue;
      const bytes = fs.readFileSync(full);
      if (bytes.length >= 4 && MACH_O_MAGIC.has(bytes.subarray(0, 4).toString('hex'))) {
        rows.push({ path: path.relative(treeDir, full), sha256: crypto.createHash('sha256').update(bytes).digest('hex') });
      }
    }
  };
  walk(treeDir);
  return rows.sort((a, b) => (a.path < b.path ? -1 : 1));
}

function pinnedComponents(arch) {
  const out = execFileSync('bash', [path.join(PAYLOAD_DIR, 'build-payload.sh'), '--pins', arch], { encoding: 'utf8' });
  return JSON.parse(out).components;
}

function buildManifest(payloadDir) {
  const trees = {};
  for (const arch of TREE_ARCHES) {
    const dir = path.join(payloadDir, `payload-${arch}`);
    if (!fs.statSync(dir).isDirectory()) throw new Error(`payload tree missing: ${dir}`);
    const binaries = machoHashes(dir);
    if (binaries.length === 0) throw new Error(`no Mach-O files in ${dir}`);
    trees[arch] = { components: pinnedComponents(arch), binaries };
  }
  const lock = fs.readFileSync(path.join(PAYLOAD_DIR, 'runtime.lock'), 'utf8');
  return { schema: 1, signing_team: SIGNING_TEAM_ID, trees, wheels: lockWheels(lock) };
}

function writeManifest(payloadDir) {
  const file = path.join(payloadDir, MANIFEST_NAME);
  fs.writeFileSync(file, `${JSON.stringify(buildManifest(payloadDir), null, 2)}\n`);
  return file;
}

module.exports = { lockWheels, machoHashes, buildManifest, writeManifest, MANIFEST_NAME };
