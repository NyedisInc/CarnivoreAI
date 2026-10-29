'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { execFileSync } = require('node:child_process');

const PAYLOAD_DIR = path.join(__dirname, '..', 'payload');
const KEY_FILE = '.payload-cache-key';
const RECIPE_FILES = ['runtime.lock', 'runtime.in', 'build-payload.sh'];

function readPins(arch) {
  return execFileSync('bash', [path.join(PAYLOAD_DIR, 'build-payload.sh'), '--pins', arch], { encoding: 'utf8' });
}

function cacheKey(arch, opts = {}) {
  const dir = opts.payloadDir || PAYLOAD_DIR;
  const h = crypto.createHash('sha256');
  h.update(`arch:${arch}\n`);
  for (const f of RECIPE_FILES) {
    const bytes = fs.readFileSync(path.join(dir, f));
    h.update(`${f}:${bytes.length}\n`).update(bytes).update('\n');
  }
  h.update(`pins:${opts.pins !== undefined ? opts.pins : readPins(arch)}\n`);
  return h.digest('hex');
}

function isReusable(out, arch, key) {
  const tree = path.join(out, `payload-${arch}`);
  try {
    return fs.readFileSync(path.join(tree, KEY_FILE), 'utf8').trim() === key
      && fs.statSync(path.join(tree, 'PAYLOAD.json')).isFile();
  } catch (e) {
    if (e.code === 'ENOENT' || e.code === 'ENOTDIR') return false;
    throw e;
  }
}

function ensureTree({ arch, out, key, build, force = false, log = () => {} }) {
  if (!force && isReusable(out, arch, key)) {
    log(`[payload] reusing cached payload-${arch} (key ${key.slice(0, 12)})`);
    return true;
  }
  fs.mkdirSync(out, { recursive: true });
  const tmpOut = fs.mkdtempSync(path.join(out, `.tmp-${arch}-`));
  try {
    build(tmpOut);
    const built = path.join(tmpOut, `payload-${arch}`);
    fs.writeFileSync(path.join(built, KEY_FILE), `${key}\n`);
    const final = path.join(out, `payload-${arch}`);
    fs.rmSync(final, { recursive: true, force: true });
    fs.renameSync(built, final);
  } finally {
    fs.rmSync(tmpOut, { recursive: true, force: true });
  }
  log(`[payload] built payload-${arch} (key ${key.slice(0, 12)})`);
  return false;
}

module.exports = { cacheKey, isReusable, ensureTree, KEY_FILE, RECIPE_FILES };
