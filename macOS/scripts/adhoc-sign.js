'use strict';

/* codesign --verify --deep --strict */

const { execFileSync, spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { importIdentityFromEnv, parseIdentities } = require('./signing-keychain');

const AD_HOC_REQUEST = '-';

const MACH_O_MAGIC = new Set([0xfeedface, 0xfeedfacf, 0xcefaedfe, 0xcffaedfe, 0xcafebabe, 0xbebafeca]);

function run(cmd, args) {
  return execFileSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

function runBothStreams(cmd, args) {
  const result = spawnSync(cmd, args, { encoding: 'utf8' });
  if (result.error) {
    throw result.error;
  }
  if (result.status !== 0) {
    throw new Error(`${cmd} exited ${result.status}: ${(result.stderr || '').trim()}`);
  }
  return `${result.stdout || ''}\n${result.stderr || ''}`.trim();
}

const FORBIDDEN_TEAM_ID = 'MDH8UQ6H46';

function isForbiddenIdentityName(name) {
  return String(name).trimEnd().endsWith(` (${FORBIDDEN_TEAM_ID})`);
}

function chooseIdentity() {
  const requested = process.env.CLOUDE_SIGN_IDENTITY;
  if (!requested || requested === AD_HOC_REQUEST) {
    return null;
  }
  if (isForbiddenIdentityName(requested)) {
    throw new Error(`CLOUDE_SIGN_IDENTITY names an identity of team ${FORBIDDEN_TEAM_ID}, which never signs`);
  }

  let listing;
  try {
    listing = run('security', ['find-identity', '-p', 'codesigning']);
  } catch (err) {
    throw new Error(
      `CLOUDE_SIGN_IDENTITY is set to "${requested}" but the codesigning identity ` +
        `list could not be read: ${err.message}`
    );
  }

  const all = parseIdentities(listing);
  const usable = all.filter((i) => i.status === null || i.status === 'CSSMERR_TP_NOT_TRUSTED');

  const wanted = requested.toUpperCase();
  const exact =
    usable.find((i) => i.sha1 === wanted) ||
    usable.find((i) => i.name === requested) ||
    usable.find((i) => i.name.includes(requested));
  if (!exact) {
    throw new Error(
      `CLOUDE_SIGN_IDENTITY is set to "${requested}" but no installed codesigning ` +
        `identity matches it. Installed identities: ${all.map((i) => i.name).join(', ') || '(none)'}`
    );
  }
  if (isForbiddenIdentityName(exact.name)) {
    throw new Error(`CLOUDE_SIGN_IDENTITY matched "${exact.name}", an identity of team ${FORBIDDEN_TEAM_ID}, which never signs`);
  }
  return exact.sha1;
}

function isMachO(filePath) {
  let fd;
  try {
    fd = fs.openSync(filePath, 'r');
    const head = Buffer.alloc(4);
    if (fs.readSync(fd, head, 0, 4, 0) < 4) {
      return false;
    }
    return MACH_O_MAGIC.has(head.readUInt32BE(0)) || MACH_O_MAGIC.has(head.readUInt32LE(0));
  } catch (err) {
    return false;
  } finally {
    if (fd !== undefined) {
      fs.closeSync(fd);
    }
  }
}

function collectSigningTargets(appPath) {
  const looseBinaries = [];
  const nestedBundles = [];

  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isSymbolicLink()) {
        continue;
      }
      if (entry.isDirectory()) {
        if (full !== appPath && (entry.name.endsWith('.app') || entry.name.endsWith('.framework'))) {
          nestedBundles.push(full);
        }
        walk(full);
      } else if (entry.isFile() && isMachO(full)) {
        looseBinaries.push(full);
      }
    }
  }
  walk(appPath);

  const byDepthDescending = (a, b) => b.split(path.sep).length - a.split(path.sep).length;
  looseBinaries.sort(byDepthDescending);
  nestedBundles.sort(byDepthDescending);

  return [...looseBinaries, ...nestedBundles, appPath];
}

function adhocSign(appPath, identity = chooseIdentity(), keychain = null, options = {}) {
  if (identity) {
    const keychainArgs = keychain ? ['--keychain', keychain] : [];
    for (const target of collectSigningTargets(appPath)) {
      try {
        run('codesign', ['--force', options.timestamp === false ? '--timestamp=none' : '--timestamp', ...keychainArgs, '--sign', identity, target]);
      } catch (err) {
        if (/errSecInternalComponent/.test(`${err.message}${err.stderr || ''}`)) {
          throw new Error(
            `codesign could not use the private key for "${identity}" (errSecInternalComponent). ` +
              'The key is in a keychain but its partition list does not allow codesign, which is ' +
              'what a key imported from a non-GUI session looks like. Fix it once with ' +
              '`security set-key-partition-list -S apple-tool:,apple:,codesign: -s -l "<key label>" ' +
              '~/Library/Keychains/login.keychain-db`, or build with CSC_LINK instead. See docs/code-signing.md.'
          );
        }
        throw err;
      }
    }
  } else {
    run('codesign', ['--force', '--deep', '--sign', '-', '--timestamp=none', appPath]);
  }

  const sigDir = path.join(appPath, 'Contents', '_CodeSignature');
  if (!fs.existsSync(path.join(sigDir, 'CodeResources'))) {
    throw new Error(
      `signing reported success but ${sigDir}/CodeResources does not exist. ` +
        'The bundle would show "damaged and can\'t be opened" once quarantined.'
    );
  }

  run('codesign', ['--verify', '--deep', '--strict', '--verbose=2', appPath]);

  if (identity) {
    const details = runBothStreams('codesign', ['-dv', '--verbose=4', appPath]);
    const requirement = designatedRequirement(appPath);
    if (/flags=0x[0-9a-f]*\([^)]*adhoc/.test(details) || !requirementIsStable(requirement)) {
      throw new Error(
        `signed with "${identity}" but the designated requirement is not identity-anchored: ` +
          `${requirement || '(none)'}. Privacy consent would not survive the next build.`
      );
    }
  }
}

function designatedRequirement(appPath) {
  const out = runBothStreams('codesign', ['-d', '-r-', appPath]);
  const m = out.match(/designated => (.+)$/m);
  return m ? m[1].trim() : '';
}

function requirementIsStable(requirement) {
  return (
    requirement !== '' &&
    !/\bcdhash\b/.test(requirement) &&
    /\b(anchor|certificate (root|leaf|\d+))\b/.test(requirement)
  );
}

async function flipFusesBeforeSigning(context) {
  const fuses = context.packager.config && context.packager.config.electronFuses;
  if (fuses == null) {
    return;
  }
  await context.packager.addElectronFuses(context, await context.packager.generateFuseConfig(fuses));
  console.log('[adhoc-sign] flipped the Electron fuses before signing');
}

module.exports = async function adhocSignHook(context) {
  if (context.electronPlatformName !== 'darwin') {
    return;
  }

  const appName = `${context.packager.appInfo.productFilename}.app`;
  const appPath = path.join(context.appOutDir, appName);

  if (!fs.existsSync(appPath)) {
    throw new Error(`afterPack: expected bundle not found at ${appPath}`);
  }

  if (/-(x64|arm64)-temp$/.test(path.basename(context.appOutDir))) {
    console.log(`[adhoc-sign] skipped: ${appPath} is one half of a universal build, the merged app is signed`);
    return;
  }

  if (context.packager.platformSpecificBuildOptions.identity) {
    if (!process.env.CSC_KEYCHAIN) {
      throw new Error(
        'mac.identity is set but CSC_KEYCHAIN is not: electron-builder would search every keychain. ' +
          'Build a release with macOS/scripts/release-build.sh; a plain npm run package leaves mac.identity null'
      );
    }
    console.log(`[adhoc-sign] skipped: electron-builder signs ${appPath} with the Developer ID identity in ${process.env.CSC_KEYCHAIN}`);
    return;
  }

  await flipFusesBeforeSigning(context);

  const supplied = importIdentityFromEnv();
  try {
    const identity = supplied ? supplied.identity : chooseIdentity();
    const adhocWhy = process.env.CLOUDE_SIGN_IDENTITY === AD_HOC_REQUEST
      ? 'ad hoc (CLOUDE_SIGN_IDENTITY=-)'
      : 'ad hoc (CLOUDE_SIGN_IDENTITY not set)';
    const label = supplied ? `${supplied.name} (from CSC_LINK)` : identity || adhocWhy;
    console.log(`[adhoc-sign] signing ${appPath} as ${label}`);
    adhocSign(appPath, identity, supplied ? supplied.keychain : null);
    console.log(
      identity
        ? `[adhoc-sign] signature present and verified; designated => ${designatedRequirement(appPath)}`
        : '[adhoc-sign] signature present and verified (ad-hoc, no identity)'
    );
  } finally {
    if (supplied) {
      supplied.dispose();
    }
  }
};

module.exports.adhocSign = adhocSign;
module.exports.chooseIdentity = chooseIdentity;
module.exports.AD_HOC_REQUEST = AD_HOC_REQUEST;
module.exports.collectSigningTargets = collectSigningTargets;
module.exports.designatedRequirement = designatedRequirement;
module.exports.requirementIsStable = requirementIsStable;
