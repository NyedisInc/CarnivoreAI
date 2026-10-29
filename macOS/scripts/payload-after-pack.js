'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { TREE_ARCHES } = require('../engine/payload-select');
const { writeManifest } = require('./payload-manifest');
const { cacheKey, ensureTree, KEY_FILE } = require('./payload-cache');

const BUILD_SCRIPT = path.join(__dirname, '..', 'payload', 'build-payload.sh');
const NOTICES_SCRIPT = path.join(__dirname, '..', 'payload', 'gen_notices.py');
const MAC_DIR = path.join(__dirname, '..');
const SIGN_SCRIPT = path.join(__dirname, '..', 'payload', 'sign-payload.sh');
const built = new Set();

function buildOutDir() {
  const cache = process.env.CARNIVORE_PAYLOAD_CACHE || path.join(process.env.HOME || '', '.cache', 'carnivore-payload');
  return process.env.CARNIVORE_PAYLOAD_OUT || path.join(cache, 'out');
}

function run(cmd, args) {
  const r = spawnSync(cmd, args, { stdio: 'inherit' });
  if (r.error || r.status !== 0) {
    throw new Error(`${cmd} failed (status ${r.status}${r.error ? `, ${r.error.message}` : ''})`);
  }
}

function writeNotices(appPath, trees) {
  const resources = path.join(appPath, 'Contents', 'Resources');
  const out = path.join(resources, 'THIRD-PARTY-NOTICES.txt');
  const electronDist = path.join(path.dirname(require.resolve('electron/package.json', { paths: [MAC_DIR] })), 'dist');
  run('python3', [NOTICES_SCRIPT, '--out', out, ...trees.flatMap((t) => ['--tree', t]), '--electron-dist', electronDist,
    '--chromium-out', resources, '--node-modules', path.join(MAC_DIR, 'node_modules'), '--app-package', path.join(MAC_DIR, 'package.json'),
    '--web-dir', path.join(MAC_DIR, '..', 'web'), '--client-dir', path.join(MAC_DIR, '..', 'client')]);
  return out;
}

function stagePayload(appPath) {
  const out = buildOutDir();
  const dest = path.join(appPath, 'Contents', 'Resources', 'payload');
  fs.rmSync(dest, { recursive: true, force: true });
  fs.mkdirSync(dest, { recursive: true });
  const trees = TREE_ARCHES.map((arch) => {
    if (!built.has(arch)) {
      ensureTree({ arch, out, key: cacheKey(arch), force: process.env.CARNIVORE_PAYLOAD_REBUILD === '1',
        build: (tmpOut) => run('bash', [BUILD_SCRIPT, arch, tmpOut]), log: console.log });
      built.add(arch);
    }
    const tree = path.join(dest, `payload-${arch}`);
    run('ditto', [path.join(out, `payload-${arch}`), tree]);
    fs.rmSync(path.join(tree, KEY_FILE), { force: true });
    return tree;
  });
  console.log(`[payload] wrote ${writeNotices(appPath, trees)}`);
  return trees;
}

function signPayload(appPath, identitySigned = false) {
  const sha1 = process.env.CARNIVORE_PAYLOAD_SIGN_SHA1;
  const keychain = process.env.CARNIVORE_PAYLOAD_SIGN_KEYCHAIN;
  if (!sha1 || !keychain) {
    if (identitySigned) {
      throw new Error('the app is signed with a Developer ID but CARNIVORE_PAYLOAD_SIGN_SHA1 or CARNIVORE_PAYLOAD_SIGN_KEYCHAIN is missing: the payload would ship unsigned (build with macOS/scripts/release-build.sh)');
    }
    return false;
  }
  const dest = path.join(appPath, 'Contents', 'Resources', 'payload');
  run('bash', [SIGN_SCRIPT, ...TREE_ARCHES.map((arch) => path.join(dest, `payload-${arch}`)), '--identity', sha1, '--keychain', keychain]);
  console.log(`[payload] wrote ${writeManifest(dest)}`);
  return true;
}

module.exports = { stagePayload, signPayload, buildOutDir, writeNotices };
