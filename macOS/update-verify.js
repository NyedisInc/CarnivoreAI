'use strict';


const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFile } = require('node:child_process');
const semver = require('semver');

const EXPECTED_TEAM = 'ARD6KN4BX4';
const EXPECTED_BUNDLE_ID = 'ai.carnivore.menubar';
const designatedRequirement = (team, bundleId) =>
  `identifier "${bundleId}" and anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] ` +
  `and certificate leaf[field.1.2.840.113635.100.6.1.13] and certificate leaf[subject.OU] = "${team}"`;
const PURPOSE_KEY = 'CarnivoreBuildPurpose';
const LAST_KEYLESS_VERSION = '1.16.3';
const TOOL_PATH = '/usr/bin:/bin:/usr/sbin:/sbin';
const DITTO = '/usr/bin/ditto';
const CODESIGN = '/usr/bin/codesign';
const PLUTIL = '/usr/bin/plutil';
const TOOL_TIMEOUT_MS = 120 * 1000;

function defaultRun(cmd, args) {
  return new Promise((resolve, reject) => {
    execFile(cmd, args, { timeout: TOOL_TIMEOUT_MS, maxBuffer: 8 * 1024 * 1024, env: { PATH: TOOL_PATH } }, (err, stdout, stderr) => {
      if (err) reject(Object.assign(err, { stdout, stderr })); else resolve({ stdout, stderr });
    });
  });
}

function isStrictlyNewer(candidate, current) {
  const a = semver.valid(candidate);
  const b = semver.valid(current);
  return a !== null && b !== null && semver.gt(a, b);
}

async function readStagedVersion(run, plist) {
  try {
    return await readPlistKey(run, plist, 'CarnivoreVersion');
  } catch (_absent) {
    return readPlistKey(run, plist, 'CFBundleShortVersionString');
  }
}

async function readPlistKey(run, plist, key) {
  return (await run(PLUTIL, ['-extract', key, 'raw', '-o', '-', plist])).stdout.trim();
}

/*  hidden  */
async function findBundles(fsApi, dir, sub = '') {
  const found = [];
  for (const e of await fsApi.promises.readdir(path.join(dir, sub), { withFileTypes: true })) {
    const rel = sub ? path.join(sub, e.name) : e.name;
    const isApp = e.name.toLowerCase().endsWith('.app');
    if (isApp) found.push({ rel, kind: e.isSymbolicLink() ? 'link' : (e.isDirectory() ? 'dir' : 'file') });
    else if (e.isDirectory()) found.push(...await findBundles(fsApi, dir, rel));
  }
  return found;
}

async function verifyStagedUpdate({
  zipPath, currentVersion, currentPurpose = null, expectedTeam = EXPECTED_TEAM, expectedBundleId = EXPECTED_BUNDLE_ID, run = defaultRun, fsApi = fs, tmpdir = os.tmpdir()
}) {
  let dir = null;
  let version = null;
  const refuse = (reason) => ({ ok: false, reason, version });
  try {
    if (typeof zipPath !== 'string' || zipPath === '') return refuse('no staged update file');
    dir = await fsApi.promises.mkdtemp(path.join(tmpdir, 'carnivore-update-verify-'));
    await fsApi.promises.chmod(dir, 0o700);
    try {
      await run(DITTO, ['-x', '-k', zipPath, dir]);
    } catch (err) {
      return refuse('the update zip would not unpack: ' + toMessage(err));
    }
    const apps = await findBundles(fsApi, dir);
    if (apps.length !== 1) return refuse(`the update holds ${apps.length} apps, expected exactly one`);
    const [found] = apps;
    if (found.kind !== 'dir' || found.rel !== path.basename(found.rel) || found.rel.startsWith('.')) {
      return refuse('the update app is not a plain top-level application folder');
    }
    const app = path.join(dir, found.rel);
    const plist = path.join(app, 'Contents', 'Info.plist');
    let bundleId = null;
    try {
      bundleId = await readPlistKey(run, plist, 'CFBundleIdentifier');
    } catch (err) {
      return refuse('the update bundle identifier could not be read: ' + toMessage(err));
    }
    if (bundleId !== expectedBundleId) return refuse(`the update is app ${bundleId || 'none'}, expected ${expectedBundleId}`);
    try {
      await run(CODESIGN, ['--verify', '--deep', '--strict', '--verbose=2', app]);
    } catch (err) {
      return refuse('the update signature is not valid: ' + toMessage(err));
    }
    let team = null;
    try {
      const { stdout, stderr } = await run(CODESIGN, ['-dv', '--verbose=4', app]);
      const m = /^TeamIdentifier=(\S+)/m.exec(`${stderr || ''}\n${stdout || ''}`);
      team = m ? m[1] : null;
      await run(CODESIGN, ['--verify', '--strict', `-R=${designatedRequirement(expectedTeam, expectedBundleId)}`, app]);
    } catch (err) {
      return refuse('the update is not signed by the Carnivore team: ' + toMessage(err));
    }
    if (team !== expectedTeam) return refuse(`the update is signed by team ${team || 'none'}, expected ${expectedTeam}`);
    try {
      version = await readStagedVersion(run, plist);
    } catch (err) {
      return refuse('the update version could not be read: ' + toMessage(err));
    }
    if (semver.valid(version) === null) return refuse(`the update version "${version}" is not a valid version`);
    if (semver.valid(currentVersion) === null) return refuse(`the running version "${currentVersion}" is not a valid version`);
    if (!isStrictlyNewer(version, currentVersion)) return refuse(`the update ${version} is not newer than ${currentVersion}`);
    let purpose = null;
    try {
      purpose = await readPlistKey(run, plist, PURPOSE_KEY);
    } catch (_absent) {
      purpose = null;
    }
    const proofOverProof = purpose === 'update-proof' && currentPurpose === 'update-proof';
    if (!proofOverProof && (purpose === null ? semver.gt(version, LAST_KEYLESS_VERSION) : purpose !== 'release')) {
      return refuse(`the update is a ${purpose || 'keyless'} build, not a release build`);
    }
    return { ok: true, reason: null, version };
  } catch (err) {
    return refuse('the update check failed: ' + toMessage(err));
  } finally {
    if (dir !== null) {
      try {
        await fsApi.promises.rm(dir, { recursive: true, force: true });
      } catch (_gone) {
      }
    }
  }
}

function toMessage(err) {
  const text = (err && (err.stderr || err.message)) || String(err);
  return String(text).trim().split('\n')[0].slice(0, 200);
}

module.exports = { EXPECTED_TEAM, EXPECTED_BUNDLE_ID, PURPOSE_KEY, verifyStagedUpdate, isStrictlyNewer, readStagedVersion };
