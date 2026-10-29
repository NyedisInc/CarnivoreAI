'use strict';


const { execFileSync, spawnSync } = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ENV_LINK = 'CSC_LINK';
const ENV_PASSWORD = 'CSC_KEY_PASSWORD';
const END_SIGNALS = ['SIGINT', 'SIGTERM', 'SIGHUP', 'SIGQUIT'];
const KEY_PARTITIONS = 'apple-tool:,apple:,codesign:';
const SECURITY_LINE_LIMIT = 4095;
const MAX_PASSWORD_BYTES = 1024;

function run(cmd, args) {
  try {
    return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  } catch (err) {
    const stderr = (err.stderr || '').toString().trim();
    throw new Error(`${cmd} ${args[0]} failed: ${stderr || err.message}`);
  }
}

function quoteForSecurity(value, what) {
  if (typeof value !== 'string' || value === '') {
    throw new Error(`${what} is empty and cannot be passed to security -i`);
  }
  if (/[\n\r\0]/.test(value)) {
    throw new Error(`${what} holds a newline, carriage return or NUL, which security -i cannot take safely`);
  }
  return `"${value.replace(/[\\"]/g, '\\$&')}"`;
}

function runInteractive(name, command) {
  if (Buffer.byteLength(command, 'utf8') + 1 > SECURITY_LINE_LIMIT) {
    throw new Error(`security ${name} command line exceeds the ${SECURITY_LINE_LIMIT}-byte line security -i reads whole`);
  }
  const res = spawnSync('security', ['-i'], {
    input: `${command}\n`,
    encoding: 'utf8',
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  if (res.error) {
    throw new Error(`security ${name} failed: ${res.error.message}`);
  }
  if (res.status !== 0) {
    throw new Error(`security ${name} failed: ${(res.stderr || '').trim() || `exit ${res.status}`}`);
  }
  return (res.stdout || '').trim();
}

function parseIdentities(listing) {
  const seen = new Map();
  for (const line of listing.split('\n')) {
    const m = line.match(/^\s*\d+\)\s+([0-9A-F]{40})\s+"(.+?)"(?:\s+\((CSSMERR_[A-Z_]+)\))?\s*$/);
    if (m && !seen.has(m[1])) {
      seen.set(m[1], { sha1: m[1], name: m[2], status: m[3] || null });
    }
  }
  return [...seen.values()];
}

/* neither an existing file nor base64 */
function materializeP12(link, dir) {
  const asPath = link.startsWith('file://') ? decodeURIComponent(link.slice(7)) : link;
  if (fs.existsSync(asPath)) {
    return asPath;
  }
  const compact = link.replace(/\s+/g, '');
  if (!/^[A-Za-z0-9+/]+={0,2}$/.test(compact)) {
    throw new Error(`${ENV_LINK} is neither an existing file nor base64-encoded .p12 data`);
  }
  const p12Path = path.join(dir, 'identity.p12');
  fs.writeFileSync(p12Path, Buffer.from(compact, 'base64'), { mode: 0o600 });
  return p12Path;
}

function userSearchList() {
  return run('security', ['list-keychains', '-d', 'user'])
    .split('\n')
    .map((l) => l.trim().replace(/^"|"$/g, ''))
    .filter(Boolean);
}

function sameKeychain(a, b) {
  if (a === b) {
    return true;
  }
  try {
    return fs.realpathSync(a) === fs.realpathSync(b);
  } catch (err) {
    if (err.code === 'ENOENT') {
      return false;
    }
    throw err;
  }
}

function importIdentityFromEnv(env = process.env) {
  const link = env[ENV_LINK];
  if (!link) {
    return null;
  }
  const password = env[ENV_PASSWORD];
  if (password === undefined) {
    throw new Error(`${ENV_LINK} is set but ${ENV_PASSWORD} is not`);
  }

  if (typeof password === 'string' && Buffer.byteLength(password, 'utf8') > MAX_PASSWORD_BYTES) {
    throw new Error(`${ENV_PASSWORD} is longer than ${MAX_PASSWORD_BYTES} bytes, which security -i cannot take safely`);
  }
  const quotedPassword = quoteForSecurity(password, ENV_PASSWORD);

  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'carnivore-sign-'));
  fs.chmodSync(dir, 0o700);
  const keychain = path.join(dir, 'signing.keychain-db');
  const keychainPassword = crypto.randomBytes(24).toString('hex');
  let created = false;
  let added = false;
  let disposed = false;
  const ignoreSignal = () => {};

  const unlist = () => {
    for (let attempt = 0; ; attempt += 1) {
      try {
        const current = userSearchList();
        const kept = current.filter((entry) => !sameKeychain(entry, keychain));
        if (kept.length !== current.length) {
          run('security', ['list-keychains', '-d', 'user', '-s', ...kept]);
        }
        return;
      } catch (err) {
        if (attempt >= 1) {
          throw err;
        }
        Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 1000);
      }
    }
  };

  const dispose = () => {
    if (disposed) {
      return;
    }
    disposed = true;
    process.removeListener('exit', dispose);
    for (const signal of END_SIGNALS) {
      process.removeListener(signal, onSignal);
      process.on(signal, ignoreSignal);
    }
    try {
      if (added) {
        unlist();
      }
    } finally {
      if (created) {
        try {
          run('security', ['delete-keychain', keychain]);
        } catch (err) {
          console.warn(`[signing-keychain] delete-keychain failed: ${err.message}`);
        }
      }
      fs.rmSync(dir, { recursive: true, force: true });
      for (const signal of END_SIGNALS) {
        process.removeListener(signal, ignoreSignal);
      }
    }
  };

  const onSignal = (signal) => {
    dispose();
    process.kill(process.pid, signal);
  };
  process.once('exit', dispose);
  for (const signal of END_SIGNALS) {
    process.once(signal, onSignal);
  }

  try {
    const p12 = materializeP12(link, dir);
    const q = (value, what) => quoteForSecurity(value, what);
    const quotedKeychain = q(keychain, 'keychain path');
    const quotedKeychainPassword = q(keychainPassword, 'keychain password');
    runInteractive('create-keychain', `create-keychain -p ${quotedKeychainPassword} ${quotedKeychain}`);
    created = true;
    runInteractive('set-keychain-settings', `set-keychain-settings ${quotedKeychain}`);
    runInteractive('unlock-keychain', `unlock-keychain -p ${quotedKeychainPassword} ${quotedKeychain}`);
    runInteractive(
      'import',
      `import ${q(p12, 'p12 path')} -k ${quotedKeychain} -f pkcs12 -P ${quotedPassword} -T /usr/bin/codesign`
    );
    runInteractive(
      'set-key-partition-list',
      `set-key-partition-list -S ${KEY_PARTITIONS} -s -k ${quotedKeychainPassword} ${quotedKeychain}`
    );
    added = true;
    run('security', ['list-keychains', '-d', 'user', '-s', ...userSearchList(), keychain]);

    const found = parseIdentities(run('security', ['find-identity', '-p', 'codesigning', keychain]));
    if (found.length !== 1) {
      throw new Error(`expected exactly one codesigning identity in ${ENV_LINK}, found ${found.length}`);
    }
    return { identity: found[0].sha1, name: found[0].name, keychain, dispose };
  } catch (err) {
    dispose();
    throw err;
  }
}

module.exports = { importIdentityFromEnv, parseIdentities, materializeP12, quoteForSecurity, ENV_LINK, ENV_PASSWORD };
