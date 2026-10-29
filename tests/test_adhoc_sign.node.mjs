// What this file can and cannot cover:

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');
const macDir = path.join(repoRoot, 'macOS');
const hookPath = path.join(macDir, 'scripts', 'adhoc-sign.js');
const require = createRequire(import.meta.url);

let failures = 0;
let passes = 0;
let skips = 0;
const queue = [];

function test(name, fn) {
    queue.push([name, fn]);
}

async function runQueue() {
    for (const [name, fn] of queue) {
        try {
            await fn();
            passes += 1;
        } catch (err) {
            if (err && err.skip) {
                skips += 1;
                console.log(`SKIP ${name}: ${err.message}`);
                continue;
            }
            failures += 1;
            console.error(`FAIL ${name}: ${err && err.message}`);
        }
    }
}

/** Mark the current test as skipped rather than passed. */
function skip(reason) {
    const e = new Error(reason);
    e.skip = true;
    throw e;
}


test('package.json wires the afterPack hook to a file that exists', () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8'));
    assert.equal(
        pkg.build.afterPack,
        'scripts/after-pack.js',
        'build.afterPack must point at scripts/after-pack.js (R2-02), which stages the payload and then runs the ad-hoc signing hook. Without it ' +
            'electron-builder skips signing and ships a bundle macOS calls damaged.'
    );
    assert.ok(fs.existsSync(hookPath), `${hookPath} must exist`);
    assert.match(
        fs.readFileSync(path.join(macDir, 'scripts', 'after-pack.js'), 'utf8'),
        /require\('\.\/adhoc-sign'\)/,
        'after-pack.js must delegate to the ad-hoc signing hook'
    );
});

test('the hook exports a function and its signing primitive', () => {
    const mod = require(hookPath);
    assert.equal(typeof mod, 'function', 'afterPack hooks are called as functions');
    assert.equal(typeof mod.adhocSign, 'function', 'adhocSign must be exported for this test');
});

test('the hook is not shipped inside the app bundle', () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8'));
    assert.ok(
        pkg.build.files.includes('!scripts/**'),
        'build tooling must be excluded from the packaged asar'
    );
});


test('package.json version is not the upstream 0.8.1', () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8'));
    assert.notEqual(
        pkg.version,
        '0.8.1',
        'our DMG must not be named identically to upstream\'s published 0.8.1 asset'
    );
    assert.match(pkg.version, /^\d+\.\d+\.\d+$/, 'version must be a plain semver triple');
});

test('the app version reaches the web client from package.json alone', () => {
    const sm = fs.readFileSync(path.join(macDir, 'server-manager.js'), 'utf8');
    assert.ok(
        sm.includes('CLOUDE_APP_VERSION') && sm.includes('app.getVersion()'),
        'server-manager.js must inject app.getVersion() as CLOUDE_APP_VERSION'
    );
    const versionPy = fs.readFileSync(path.join(repoRoot, 'src', 'core', 'version.py'), 'utf8');
    assert.ok(
        versionPy.includes('CLOUDE_APP_VERSION'),
        'src/core/version.py must read CLOUDE_APP_VERSION'
    );
    const mainPy = fs.readFileSync(path.join(repoRoot, 'src', 'main.py'), 'utf8');
    assert.ok(
        mainPy.includes('resolve_version'),
        'src/main.py must delegate to src/core/version.py::resolve_version'
    );
    const html = fs.readFileSync(path.join(repoRoot, 'client', 'index.html'), 'utf8');
    assert.ok(html.includes('{{VERSION}}'), 'client/index.html must keep the {{VERSION}} token');
});


test('adhocSign seals a real bundle and the signature verifies', () => {
    if (os.platform() !== 'darwin') {
        skip('codesign only exists on macOS');
    }

    const { adhocSign } = require(hookPath);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'adhoc-sign-test-'));
    const appPath = path.join(tmp, 'Fixture.app');
    const macOSDir = path.join(appPath, 'Contents', 'MacOS');
    fs.mkdirSync(macOSDir, { recursive: true });

    fs.copyFileSync('/bin/echo', path.join(macOSDir, 'Fixture'));
    fs.writeFileSync(
        path.join(appPath, 'Contents', 'Info.plist'),
        `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Fixture</string>
<key>CFBundleIdentifier</key><string>com.cloudecode.signfixture</string>
<key>CFBundleName</key><string>Fixture</string>
<key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
`
    );

    const sealed = path.join(appPath, 'Contents', '_CodeSignature', 'CodeResources');
    assert.ok(!fs.existsSync(sealed), 'fixture must start unsigned');

    adhocSign(appPath);

    assert.ok(fs.existsSync(sealed), 'Contents/_CodeSignature/CodeResources must exist after signing');

    const out = execFileSync('codesign', ['--verify', '--deep', '--strict', '--verbose=2', appPath], {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'pipe'],
    });
    assert.doesNotThrow(() => out);

    const info = spawnSync('codesign', ['-dvv', appPath], { encoding: 'utf8' });
    const report = `${info.stdout || ''}${info.stderr || ''}`;
    assert.ok(
        /^Executable=/m.test(report),
        `codesign -dvv produced no readable report, so nothing about the ` +
        `signature was measured; got: ${report.trim()}`
    );

    const { chooseIdentity } = require(hookPath);
    const identity = chooseIdentity();
    if (identity === null) {
        assert.ok(
            /Signature=adhoc/.test(report),
            `no codesigning identity is installed, so the hook must fall back ` +
            `to ad hoc, got: ${report.trim()}`
        );
    } else {
        assert.ok(
            !/Signature=adhoc/.test(report),
            `the hook chose the installed identity ${JSON.stringify(identity)}, ` +
            `so the bundle must NOT be ad-hoc signed, got: ${report.trim()}`
        );
        assert.ok(
            /^Authority=/m.test(report),
            `a certificate-signed bundle must report an Authority chain, ` +
            `got: ${report.trim()}`
        );
    }

    fs.rmSync(tmp, { recursive: true, force: true });
});


const keychainPath = path.join(macDir, 'scripts', 'signing-keychain.js');

test('parseIdentities keeps untrusted self-signed identities and dedupes', () => {
    const { parseIdentities } = require(keychainPath);
    const sha = '93F075F0EB4E9E1B0D7D1569E2F853ACF26ABCDE';
    const listing = [
        'Policy: Code Signing',
        '  Matching identities',
        `  1) ${sha} "Carnivore Development" (CSSMERR_TP_NOT_TRUSTED)`,
        `  2) ${'A'.repeat(40)} "Apple Development: Someone (TEAMID1234)"`,
        '     2 identities found',
        '  Valid identities only',
        `  1) ${'A'.repeat(40)} "Apple Development: Someone (TEAMID1234)"`,
    ].join('\n');
    const ids = parseIdentities(listing);
    assert.equal(ids.length, 2, 'one entry per distinct SHA-1');
    assert.deepEqual(ids[0], { sha1: sha, name: 'Carnivore Development', status: 'CSSMERR_TP_NOT_TRUSTED' });
    assert.equal(ids[1].status, null, 'a trusted identity carries no status');
});

test('requirementIsStable refuses a cdhash and accepts an identity anchor', () => {
    const { requirementIsStable } = require(hookPath);
    assert.equal(requirementIsStable('cdhash H"8aeb1ef029e91b25334e7d8a1f95ad2aadae6089"'), false);
    assert.equal(requirementIsStable(''), false);
    assert.equal(requirementIsStable('identifier "ai.carnivore.menubar"'), false, 'an identifier alone anchors nothing');
    assert.equal(
        requirementIsStable('identifier "ai.carnivore.menubar" and certificate root = H"93f075f0eb4e9e1b0d7d1569e2f853acf26abcde"'),
        true
    );
    assert.equal(
        requirementIsStable('identifier "x" and anchor apple generic and certificate leaf[subject.CN] = "y"'),
        true
    );
});

test('no CSC_LINK means no supplied identity, and a half-set pair is refused', () => {
    const { importIdentityFromEnv } = require(keychainPath);
    assert.equal(importIdentityFromEnv({}), null, 'unset CSC_LINK must fall through to the ladder');
    assert.throws(
        () => importIdentityFromEnv({ CSC_LINK: '/nonexistent.p12' }),
        /CSC_KEY_PASSWORD/,
        'a certificate without its password must fail loudly, never degrade to ad hoc'
    );
});

test('materializeP12 decodes base64 and refuses junk', () => {
    const { materializeP12 } = require(keychainPath);
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'p12-mat-test-'));
    const out = materializeP12(Buffer.from('not really a p12').toString('base64'), tmp);
    assert.equal(fs.readFileSync(out, 'utf8'), 'not really a p12');
    assert.equal(fs.statSync(out).mode & 0o777, 0o600, 'decoded key material must be owner-only');
    assert.throws(() => materializeP12('this is not base64 !!', tmp), /neither an existing file nor base64/);
    fs.rmSync(tmp, { recursive: true, force: true });
});

test('a self-signed .p12 via CSC_LINK gives two different builds ONE requirement', async () => {
    if (os.platform() !== 'darwin') {
        skip('codesign only exists on macOS');
    }
    if (!fs.existsSync('/usr/bin/openssl')) {
        skip('no /usr/bin/openssl to mint a throwaway certificate');
    }
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'selfsign-test-'));
    const ossl = (args) => execFileSync('/usr/bin/openssl', args, { cwd: tmp, stdio: ['ignore', 'pipe', 'pipe'] });
    fs.writeFileSync(path.join(tmp, 'c.cnf'), [
        '[req]', 'distinguished_name=dn', 'prompt=no', 'x509_extensions=v3',
        '[dn]', 'CN=Carnivore Test Signing',
        '[v3]', 'basicConstraints=critical,CA:false', 'keyUsage=critical,digitalSignature',
        'extendedKeyUsage=critical,codeSigning', '',
    ].join('\n'));
    ossl(['req', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'k.pem', '-out', 'c.pem', '-days', '2', '-config', 'c.cnf']);
    const password = `pw${process.pid}${Date.now()}`;
    ossl(['pkcs12', '-export', '-inkey', 'k.pem', '-in', 'c.pem', '-out', 't.p12', '-passout', `pass:${password}`]);

    const makeApp = (dir, marker) => {
        const app = path.join(dir, 'Carnivore.app');
        fs.mkdirSync(path.join(app, 'Contents', 'MacOS'), { recursive: true });
        fs.mkdirSync(path.join(app, 'Contents', 'Resources'), { recursive: true });
        fs.copyFileSync('/bin/echo', path.join(app, 'Contents', 'MacOS', 'Carnivore'));
        fs.writeFileSync(path.join(app, 'Contents', 'Resources', 'marker.txt'), marker);
        fs.writeFileSync(path.join(app, 'Contents', 'Info.plist'),
            '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>' +
            '<key>CFBundleExecutable</key><string>Carnivore</string>' +
            '<key>CFBundleIdentifier</key><string>ai.carnivore.signtest</string>' +
            '<key>CFBundlePackageType</key><string>APPL</string></dict></plist>');
        return app;
    };
    const hook = require(hookPath);
    const env = { CSC_LINK: process.env.CSC_LINK, CSC_KEY_PASSWORD: process.env.CSC_KEY_PASSWORD };
    const apps = [];
    try {
        process.env.CSC_LINK = path.join(tmp, 't.p12');
        process.env.CSC_KEY_PASSWORD = password;
        for (const [name, marker] of [['A', 'build one'], ['B', 'build two']]) {
            const dir = path.join(tmp, name);
            apps.push(makeApp(dir, marker));
            await hook({ electronPlatformName: 'darwin', appOutDir: dir, packager: { appInfo: { productFilename: 'Carnivore' }, platformSpecificBuildOptions: { identity: null } } });
        }
        delete process.env.CSC_LINK;
        delete process.env.CSC_KEY_PASSWORD;
        const adhocDir = path.join(tmp, 'C');
        apps.push(makeApp(adhocDir, 'build one'));
        hook.adhocSign(apps[2], null);
    } finally {
        for (const [k, v] of Object.entries(env)) {
            if (v === undefined) delete process.env[k]; else process.env[k] = v;
        }
    }

    const [reqA, reqB, reqC] = apps.map((a) => hook.designatedRequirement(a));
    assert.ok(reqA, 'build A must carry a designated requirement');
    assert.equal(reqA, reqB, 'two different builds signed by one certificate must share one requirement');
    assert.ok(!/cdhash/.test(reqA), `the requirement must pin no cdhash, got ${reqA}`);
    const satisfies = (app) => spawnSync('codesign', ['-v', '-R', `=${reqA}`, app]).status === 0;
    assert.ok(satisfies(apps[0]) && satisfies(apps[1]), 'both builds must satisfy the shared requirement');
    assert.ok(/cdhash/.test(reqC), `the ad-hoc control must pin a cdhash, got ${reqC}`);
    assert.equal(satisfies(apps[2]), false, 'an ad-hoc build must fail the certificate requirement');
    fs.rmSync(tmp, { recursive: true, force: true });
});

function makeFixtureBundle() {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'adhoc-sign-test-'));
    const appPath = path.join(tmp, 'Fixture.app');
    const macOSDir = path.join(appPath, 'Contents', 'MacOS');
    fs.mkdirSync(macOSDir, { recursive: true });
    fs.copyFileSync('/bin/echo', path.join(macOSDir, 'Fixture'));
    fs.writeFileSync(
        path.join(appPath, 'Contents', 'Info.plist'),
        `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Fixture</string>
<key>CFBundleIdentifier</key><string>com.cloudecode.signfixture</string>
<key>CFBundleName</key><string>Fixture</string>
<key>CFBundlePackageType</key><string>APPL</string>
</dict></plist>
`
    );
    return { tmp, appPath };
}

function readSignature(appPath) {
    const info = spawnSync('codesign', ['-dvv', appPath], { encoding: 'utf8' });
    const report = `${info.stdout || ''}${info.stderr || ''}`;
    assert.ok(
        /^Executable=/m.test(report),
        `codesign -dvv produced no readable report, so nothing about the ` +
        `signature was measured; got: ${report.trim()}`
    );
    return report;
}

function loadHookWith(handler) {
    const cp = require('node:child_process');
    const real = { execFileSync: cp.execFileSync, spawnSync: cp.spawnSync };
    const calls = [];
    for (const [name, fn] of Object.entries(real)) {
        cp[name] = (cmd, args = [], ...rest) => {
            calls.push([cmd, ...args]);
            return handler(cmd, args) ?? fn(cmd, args, ...rest);
        };
    }
    delete require.cache[hookPath];
    try {
        return { hook: require(hookPath), calls };
    } finally {
        Object.assign(cp, real);
        delete require.cache[hookPath];
    }
}

async function withSignIdentity(value, fn) {
    const saved = process.env.CLOUDE_SIGN_IDENTITY;
    const set = (v) => {
        if (v === undefined) {
            delete process.env.CLOUDE_SIGN_IDENTITY;
        } else {
            process.env.CLOUDE_SIGN_IDENTITY = v;
        }
    };
    set(value);
    try {
        return await fn();
    } finally {
        set(saved);
    }
}

test('adhocSign seals a real bundle and the signature verifies', () => {
    if (os.platform() !== 'darwin') {
        skip('codesign only exists on macOS');
    }

    const { adhocSign } = require(hookPath);
    const { tmp, appPath } = makeFixtureBundle();

    const sealed = path.join(appPath, 'Contents', '_CodeSignature', 'CodeResources');
    assert.ok(!fs.existsSync(sealed), 'fixture must start unsigned');

    adhocSign(appPath);

    assert.ok(fs.existsSync(sealed), 'Contents/_CodeSignature/CodeResources must exist after signing');

    const out = execFileSync('codesign', ['--verify', '--deep', '--strict', '--verbose=2', appPath], {
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'pipe'],
    });
    assert.doesNotThrow(() => out);

    const report = readSignature(appPath);

    const { chooseIdentity } = require(hookPath);
    const identity = chooseIdentity();
    if (identity === null) {
        assert.ok(
            /Signature=adhoc/.test(report),
            `CLOUDE_SIGN_IDENTITY is not set, so the hook must sign ad hoc, ` +
            `got: ${report.trim()}`
        );
    } else {
        assert.ok(
            !/Signature=adhoc/.test(report),
            `the hook chose the installed identity ${JSON.stringify(identity)}, ` +
            `so the bundle must NOT be ad-hoc signed, got: ${report.trim()}`
        );
        assert.ok(
            /^Authority=/m.test(report),
            `a certificate-signed bundle must report an Authority chain, ` +
            `got: ${report.trim()}`
        );
    }

    fs.rmSync(tmp, { recursive: true, force: true });
});

test('CLOUDE_SIGN_IDENTITY="-" signs ad hoc and never asks the keychain for anything', async () => {
    if (os.platform() !== 'darwin') {
        skip('codesign only exists on macOS');
    }

    const { tmp, appPath } = makeFixtureBundle();
    const { hook, calls } = loadHookWith((cmd, args) => {
        if (cmd === 'security') {
            throw new Error(`refused: security ${args.join(' ')}`);
        }
        const sign = args.indexOf('--sign');
        if (cmd === 'codesign' && sign !== -1 && args[sign + 1] !== '-') {
            throw new Error(`refused: codesign with identity ${args[sign + 1]}`);
        }
        return undefined;
    });

    await withSignIdentity('-', () =>
        hook({ electronPlatformName: 'darwin', appOutDir: tmp, packager: { appInfo: { productFilename: 'Fixture' }, platformSpecificBuildOptions: { identity: null } } })
    );

    const signs = calls.filter(([cmd, ...args]) => cmd === 'codesign' && args.includes('--sign'));
    assert.ok(signs.length > 0, 'the hook started no signing command, so nothing was measured');
    assert.deepEqual(calls.filter(([cmd]) => cmd === 'security'), [], 'an ad hoc request must never run security');
    for (const call of signs) {
        assert.equal(call[call.indexOf('--sign') + 1], '-', `an ad hoc request must sign ad hoc: ${call.join(' ')}`);
    }
    assert.ok(/Signature=adhoc/.test(readSignature(appPath)), 'the bundle must be ad hoc signed');

    fs.rmSync(tmp, { recursive: true, force: true });
});

test('a plain build signs ad hoc and never asks the keychain for an identity', async () => {
    const listing =
        `  1) ${'A'.repeat(40)} "Developer ID Application: Fixture Person (FIXTURE01)"\n` +
        `  2) ${'B'.repeat(40)} "Apple Development: Fixture Person (FIXTURE01)"\n` +
        `  3) ${'C'.repeat(40)} "Carnivore Development" (CSSMERR_TP_NOT_TRUSTED)\n` +
        '     2 valid identities found';
    const { hook, calls } = loadHookWith((cmd, args) => {
        if (cmd === 'security') {
            return listing;
        }
        throw new Error(`refused: ${cmd} ${args.join(' ')}`);
    });

    for (const value of [undefined, '']) {
        await withSignIdentity(value, () => {
            assert.equal(hook.chooseIdentity(), null, `CLOUDE_SIGN_IDENTITY=${JSON.stringify(value)} must mean ad hoc`);
        });
    }
    assert.deepEqual(calls, [], 'a plain build must never run security');

    await withSignIdentity('Carnivore Development', () => {
        assert.equal(hook.chooseIdentity(), 'C'.repeat(40));
    });
    assert.deepEqual(calls, [['security', 'find-identity', '-p', 'codesigning']]);
});

test('CLOUDE_SIGN_IDENTITY opts in to a certificate, and a name that matches nothing fails', async () => {
    let listing =
        `  1) ${'A'.repeat(40)} "Apple Development: Fixture Person (FIXTURE01)"\n` +
        '     1 valid identities found';
    const { hook, calls } = loadHookWith((cmd, args) => {
        if (cmd === 'security') {
            return listing;
        }
        throw new Error(`refused: ${cmd} ${args.join(' ')}`);
    });

    await withSignIdentity('Fixture Person', () => {
        assert.equal(hook.chooseIdentity(), 'A'.repeat(40));
    });
    assert.deepEqual(calls, [['security', 'find-identity', '-p', 'codesigning']]);

    await withSignIdentity('Nobody Installed', () => {
        assert.throws(() => hook.chooseIdentity(), /no installed codesigning identity matches it/);
    });

    listing = '     0 valid identities found';
    await withSignIdentity('Fixture Person', () => {
        assert.throws(() => hook.chooseIdentity(), /Installed identities: \(none\)/);
    });
});


test('release workflow still verifies the published DMG signature', () => {
    const wf = fs.readFileSync(
        path.join(repoRoot, '.github', 'workflows', 'release.yml'),
        'utf8'
    );
    assert.ok(
        wf.includes('Verify the DMG is properly signed'),
        'the workflow must verify the DMG it publishes'
    );
    assert.ok(
        wf.includes('_CodeSignature/CodeResources'),
        'the workflow must assert the sealed resource directory exists'
    );
    assert.ok(
        wf.includes('codesign --verify --deep --strict'),
        'the workflow must strictly verify the signature'
    );
    assert.ok(
        wf.includes('CSC_LINK: ${{ secrets.MAC_CERT_P12_BASE64 }}') &&
            wf.includes('CSC_KEY_PASSWORD: ${{ secrets.MAC_CERT_PASSWORD }}'),
        'the build step must hand the signing secrets to the afterPack hook'
    );
    assert.ok(
        wf.includes('cdhash'),
        'the workflow must assert a certificate-signed DMG pins no cdhash'
    );
});


function runWithStubSecurity(scenario) {
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'stub-security-'));
    const state = path.join(tmp, 'list.txt');
    fs.writeFileSync(state, '/Users/x/Library/Keychains/login.keychain-db\n/Library/Keychains/System.keychain\n');
    const original = fs.readFileSync(state, 'utf8');
    const bin = path.join(tmp, 'bin');
    fs.mkdirSync(bin);
    fs.writeFileSync(path.join(bin, 'security'), [
        '#!/bin/bash',
        'case "$1" in',
        '  list-keychains) if [ "$3" = "-s" ]; then shift 3; printf "%s\\n" "$@" > "$STUB_STATE"; else cat "$STUB_STATE"; fi ;;',
        '  find-identity) [ -n "$STUB_NO_IDENTITY" ] || echo "  1) ' + 'B'.repeat(40) + ' \\"Carnivore Development\\""; ;;',
        'esac', 'exit 0', ''].join('\n'), { mode: 0o755 });
    fs.writeFileSync(path.join(tmp, 'a.p12'), 'x');
    const script = path.join(tmp, 'run.cjs');
    fs.writeFileSync(script, `const k = require(${JSON.stringify(keychainPath)});
const env = { CSC_LINK: ${JSON.stringify(path.join(tmp, 'a.p12'))}, CSC_KEY_PASSWORD: 'pw' };
${scenario}`);
    const result = spawnSync(process.execPath, [script], {
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, STUB_STATE: state, ...(scenario.includes('NOID') ? { STUB_NO_IDENTITY: '1' } : {}) },
        encoding: 'utf8',
    });
    const after = fs.readFileSync(state, 'utf8');
    fs.rmSync(tmp, { recursive: true, force: true });
    return { original, after, result };
}

test('the search list is restored exactly after a successful pack', () => {
    const { original, after, result } = runWithStubSecurity('const s = k.importIdentityFromEnv(env); s.dispose();');
    assert.equal(result.status, 0, result.stderr);
    assert.equal(after, original);
});

test('the search list is restored when the identity lookup fails', () => {
    const { original, after, result } = runWithStubSecurity('/* NOID */ try { k.importIdentityFromEnv(env); } catch (e) { console.log("threw"); }');
    assert.match(result.stdout, /threw/);
    assert.equal(after, original);
});

test('the search list is restored when the process exits without calling dispose', () => {
    const { original, after } = runWithStubSecurity('k.importIdentityFromEnv(env); process.exit(3);');
    assert.equal(after, original, 'a dead entry would be left by an interrupted pack');
});

await runQueue();
console.log(`${passes} passed, ${failures} failed, ${skips} skipped`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
