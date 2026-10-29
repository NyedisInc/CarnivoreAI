
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { spawnSync, execFileSync } from 'node:child_process';
import { PINNED, specOf, mirror as mirrorTree, registry as registryDoc, manifestBody, GOOD_MANIFEST, hardenedBinaryFile, FRAMEWORK_UNDER_OUT } from './lib/release_mirror.mjs';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const { selectSigning, planFor, SIGNING_TEAM_ID } = require(path.join(here, '..', '..', 'macOS', 'scripts', 'signing-config.js'));
const { parseIdentities } = require(path.join(here, '..', '..', 'macOS', 'scripts', 'signing-keychain.js'));

const NYEDIS = 'AA'.repeat(20);
const OTHER = '89A226D28EA3A887349AA98E13F8E25072C7A8AD';
const nyedisLine = `  2) ${NYEDIS} "Developer ID Application: Nyedis (ARD6KN4BX4)"`;
const otherLine = `  1) ${OTHER} "Developer ID Application: Alex Callen (MDH8UQ6H46)"`;

const realKeychainTests = process.platform === 'darwin' && process.env.CARNIVORE_REAL_KEYCHAIN_TESTS === '1';
if (!realKeychainTests) {
    console.log('skip 3 real-keychain cases (set CARNIVORE_REAL_KEYCHAIN_TESTS=1 to run them)');
}

let failures = 0;
/** Run one named case, count a failure instead of aborting the rest. */
function test(name, fn) {
    try {
        fn();
        console.log(`ok   ${name}`);
    } catch (err) {
        failures += 1;
        console.log(`FAIL ${name}\n     ${err.message}`);
    }
}

test('the team id is Nyedis', () => assert.equal(SIGNING_TEAM_ID, 'ARD6KN4BX4'));

test('Nyedis identity present: Developer ID by SHA-1, with notarization', () => {
    const ids = parseIdentities([otherLine, nyedisLine].join('\n'));
    assert.equal(ids.length, 2, 'population check: both lines must parse');
    assert.deepEqual(selectSigning(ids), {
        mode: 'developer-id',
        sha1: NYEDIS,
        name: 'Developer ID Application: Nyedis (ARD6KN4BX4)',
        notarize: true,
    });
});

test('no identity at all: ad hoc, no notarization', () => {
    assert.deepEqual(selectSigning([]), { mode: 'adhoc', notarize: false });
});

test('only the wrong team present: ad hoc, the other identity is not used', () => {
    const ids = parseIdentities(otherLine);
    assert.equal(ids.length, 1, 'population check: the line must parse');
    assert.deepEqual(selectSigning(ids), { mode: 'adhoc', notarize: false });
});

test('a Nyedis identity that is not valid, or not Developer ID, is not used', () => {
    const expired = parseIdentities(`  1) ${NYEDIS} "Developer ID Application: Nyedis (ARD6KN4BX4)" (CSSMERR_TP_CERT_EXPIRED)`);
    assert.equal(expired[0].status, 'CSSMERR_TP_CERT_EXPIRED');
    assert.equal(selectSigning(expired).mode, 'adhoc');
    const appleDev = parseIdentities(`  1) ${NYEDIS} "Apple Development: Nyedis (ARD6KN4BX4)"`);
    assert.equal(selectSigning(appleDev).mode, 'adhoc');
});

test('an identity of another team (the old Psyance team and Alex Callen) is never selected', () => {
    for (const team of ['3ZVEJNEQ9G', 'MDH8UQ6H46']) {
        const ids = parseIdentities(`  1) ${NYEDIS} "Developer ID Application: Other (${team})"`);
        assert.equal(selectSigning(ids).mode, 'adhoc');
    }
});

test('a team id that only appears in the middle of a name does not match', () => {
    const ids = parseIdentities(`  1) ${NYEDIS} "Developer ID Application: ARD6KN4BX4 (MDH8UQ6H46)"`);
    assert.equal(selectSigning(ids).mode, 'adhoc');
});

test('planFor: absent is ad hoc, present-but-invalid is refused with the CSSM status', () => {
    assert.equal(planFor(parseIdentities(otherLine)).mode, 'adhoc');
    const expired = planFor(parseIdentities(`  1) ${NYEDIS} "Developer ID Application: Nyedis (ARD6KN4BX4)" (CSSMERR_TP_CERT_EXPIRED)`));
    assert.equal(expired.mode, 'invalid');
    assert.match(expired.reason, /CSSMERR_TP_CERT_EXPIRED/);
    assert.equal(planFor(parseIdentities(nyedisLine)).mode, 'developer-id');
});

const repo = path.join(here, '..', '..');
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'signing-test-'));
const bin = path.join(tmp, 'bin');
fs.mkdirSync(bin);
const stub = (name, body) => fs.writeFileSync(path.join(bin, name), `#!/bin/bash\n${body}\n`, { mode: 0o755 });
const sh = (script, args, env) =>
    spawnSync('bash', [script, ...args], { encoding: 'utf8', env: { ...process.env, HOME: tmp, PATH: `${bin}:${process.env.PATH}`, ...env } });
fs.mkdirSync(path.join(tmp, 'Library', 'Keychains'), { recursive: true });
fs.writeFileSync(path.join(tmp, 'Library', 'Keychains', 'carnivore-signing.keychain-db'), '');
const listing = (suffix) => `echo '  1) ${NYEDIS} "Developer ID Application: Nyedis (ARD6KN4BX4)"${suffix}'`;

const realPkg = JSON.parse(fs.readFileSync(path.join(repo, 'macOS', 'package.json'), 'utf8'));
const mirror = (mutate, installed) => mirrorTree(repo, tmp, mutate, installed);
const registry = (pin, pinAge, extra, latest) => registryDoc(tmp, pin, pinAge, extra, latest);
const pinNow = String(specOf(realPkg, 'electron'));
const okRegistry = registry(pinNow);
const baseMirror = mirror();
const builtBinary = hardenedBinaryFile(tmp);
const npmStub = (logCmd) => stub('npm', `if [ "$1" = view ]; then cat "\${REGISTRY_FILE:-${okRegistry}}"; exit "\${REGISTRY_RC:-0}"; fi; fw=dist; for a in "$@"; do case "$a" in -c.directories.output=*) fw="\${a#*=}";; esac; done; mkdir -p "$(dirname "$fw/${FRAMEWORK_UNDER_OUT}")"; cp "${builtBinary}" "$fw/${FRAMEWORK_UNDER_OUT}"; ${logCmd}`);

test('release-build refuses to ship ad hoc when the Nyedis certificate is expired', () => {
    stub('aws', 'echo pw');
    stub('security', `case "$1" in show-keychain-info) echo "Keychain no-timeout" >&2;; find-identity) ${listing(' (CSSMERR_TP_CERT_EXPIRED)')};; -i) cat >/dev/null;; esac; exit 0`);
    npmStub(`echo npm-ran >> "${tmp}/npm.log"`);
    const r = sh(baseMirror.releaseSh, [], {});
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /CSSMERR_TP_CERT_EXPIRED/);
    assert.equal(fs.existsSync(path.join(tmp, 'npm.log')), false, 'npm package must not run');
});

test('release-build refuses when find-identity itself fails', () => {
    stub('aws', 'echo pw');
    stub('security', `case "$1" in show-keychain-info) echo "Keychain no-timeout" >&2;; find-identity) echo boom >&2; exit 1;; -i) cat >/dev/null;; esac; exit 0`);
    const r = sh(baseMirror.releaseSh, [], {});
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /boom/, 'it failed because of find-identity, not an earlier step');
    assert.equal(fs.existsSync(path.join(tmp, 'npm.log')), false);
});

test('release-build still builds ad hoc when no Nyedis identity exists', () => {
    stub('aws', 'echo pw');
    stub('security', `case "$1" in show-keychain-info) echo "Keychain no-timeout" >&2;; find-identity) echo '  1) ${OTHER} "Developer ID Application: Alex Callen (MDH8UQ6H46)"';; -i) cat >/dev/null;; esac; exit 0`);
    const r = sh(baseMirror.releaseSh, [], {});
    assert.equal(r.status, 0, r.stderr);
    assert.ok(fs.existsSync(path.join(tmp, 'npm.log')));
});

function makeKeyAndCert(name) {
    const key = path.join(tmp, `${name}.key`);
    const cert = path.join(tmp, `${name}.pem`);
    execFileSync('openssl', ['genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048', '-out', key], { stdio: 'ignore' });
    fs.chmodSync(key, 0o600);
    execFileSync('openssl', ['req', '-new', '-x509', '-key', key, '-out', cert, '-days', '2', '-subj', '/CN=Developer ID Application: Nyedis (ARD6KN4BX4)/OU=ARD6KN4BX4'], { stdio: 'ignore' });
    return { key, cert };
}
const mine = makeKeyAndCert('mine');
const other = makeKeyAndCert('other');
const awsStub = () =>
    stub('aws', `case "$*" in *describe-secret*) echo None;; *get-secret-value*developer-id-key*) cat "$BACKUP_KEY";; *get-secret-value*) echo pw;; esac`);
const securityStub = () =>
    stub(
        'security',
        `case "$1" in show-keychain-info) echo "Keychain no-timeout" >&2;; import) echo 'SecKeychainItemImport: The specified item already exists in the keychain.' >&2; exit 1;; ` +
            `find-identity) ${listing('')};; ` +
            `dump-keychain) printf 'keychain: "k"\\nclass: 0x00000010 \\nattributes:\\n    0x00000001 <blob>="%s"\\n    0x00000006 <blob>=0x%s  "x"\\n' "$KEY_LABEL" "$MY_KLBL"; [ -n "$OTHER_LABEL" ] && printf 'keychain: "k"\\nclass: 0x00000010 \\nattributes:\\n    0x00000001 <blob>="%s"\\n    0x00000006 <blob>=0x%s  "x"\\n' "$OTHER_LABEL" "BB";; ` +
            `-i) cat >> "${tmp}/sec-i.log";; *) cat >/dev/null 2>&1 </dev/null;; esac; exit 0`
    );
const klbl = (keyFile) =>
    execFileSync('bash', ['-c', `openssl pkey -in "${keyFile}" -pubout -outform DER | openssl dgst -sha1 -r | cut -d' ' -f1 | tr a-f A-F`], { encoding: 'utf8' }).trim();
const importSh = path.join(repo, 'scripts', 'signing', 'import-developer-id.sh');
const fakeListPrefix = () => {
    const f = path.join(tmp, 'fake-user-list');
    fs.writeFileSync(f, `${path.join(tmp, 'login.keychain-db')}\n`);
    return `if [ "$1" = show-keychain-info ]; then echo "Keychain no-timeout" >&2; exit 0; fi; if [ "$1" = list-keychains ]; then case " $* " in *" -s "*) shift 4; printf '%s\\n' "$@" > "${f}";; *) while IFS= read -r l; do [ -n "$l" ] && printf '    "%s"\\n' "$l"; done < "${f}";; esac; exit 0; fi; `;
};

test('import: a backup holding a different key blocks the delete', () => {
    awsStub(); securityStub(); stub('codesign', 'exit 0');
    const k = path.join(tmp, 'use1.key');
    fs.copyFileSync(mine.key, k); fs.chmodSync(k, 0o600);
    const r = sh(importSh, [mine.cert], { CARNIVORE_DEVID_KEY: k, BACKUP_KEY: other.key });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /different key/);
    assert.ok(fs.existsSync(k), 'key file must be kept');
});

test('import: re-run with items already in the keychain finishes and deletes the key', () => {
    const k = path.join(tmp, 'use2.key');
    fs.copyFileSync(mine.key, k); fs.chmodSync(k, 0o600);
    const r = sh(importSh, [mine.cert], { CARNIVORE_DEVID_KEY: k, BACKUP_KEY: mine.key, MY_KLBL: klbl(mine.key), KEY_LABEL: 'Imported Private Key' });
    assert.equal(r.status, 0, r.stderr);
    assert.match(fs.readFileSync(path.join(tmp, 'sec-i.log'), 'utf8'), /set-key-partition-list .* -l "Imported Private Key" -k/, 'partition list limited to this key by label');
    assert.equal(fs.existsSync(k), false, 'key file deleted after verification');
});

test('import: a second private key with the same label blocks the partition rewrite', () => {
    const k = path.join(tmp, 'use3.key');
    fs.copyFileSync(mine.key, k); fs.chmodSync(k, 0o600);
    fs.rmSync(path.join(tmp, 'sec-i.log'), { force: true });
    const r = sh(importSh, [mine.cert], { CARNIVORE_DEVID_KEY: k, BACKUP_KEY: mine.key, MY_KLBL: klbl(mine.key), KEY_LABEL: 'Imported Private Key', OTHER_LABEL: 'Imported Private Key' });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /another private key/);
    assert.ok(fs.existsSync(k), 'key file must be kept');
    assert.doesNotMatch(fs.existsSync(path.join(tmp, 'sec-i.log')) ? fs.readFileSync(path.join(tmp, 'sec-i.log'), 'utf8') : '', /set-key-partition-list/);
});

if (realKeychainTests) {
    test('real keychain: the label filter rewrites one of two keys, no filter rewrites both', () => {
        const kc = path.join(tmp, 'two.keychain-db');
        const sec = (args) => spawnSync('/usr/bin/security', args, { encoding: 'utf8' });
        const labels = (out) => [...out.matchAll(/^ +0x00000001 <blob>="(.*)"$/gm)].map((m) => m[1]);
        assert.equal(sec(['create-keychain', '-p', 'tpw', kc]).status, 0);
        try {
            sec(['unlock-keychain', '-p', 'tpw', kc]);
            const p12 = path.join(tmp, 'other.p12');
            execFileSync('openssl', ['pkcs12', '-export', '-inkey', other.key, '-in', other.cert, '-name', 'Other Team', '-passout', 'pass:tp',
                '-keypbe', 'PBE-SHA1-3DES', '-certpbe', 'PBE-SHA1-3DES', '-macalg', 'sha1', '-out', p12], { stdio: 'ignore' });
            assert.equal(sec(['import', p12, '-k', kc, '-P', 'tp']).status, 0);
            assert.equal(sec(['import', mine.key, '-k', kc]).status, 0);
            const base = ['set-key-partition-list', '-S', 'apple-tool:,apple:,codesign:', '-s', '-k', 'tpw'];
            assert.deepEqual(labels(sec([...base, '-l', 'Imported Private Key', kc]).stdout), ['Imported Private Key']);
            assert.deepEqual(labels(sec([...base, kc]).stdout).sort(), ['Imported Private Key', 'Other Team']);
        } finally {
            sec(['delete-keychain', kc]);
        }
    });
}

const releaseSh = baseMirror.releaseSh;
const awsLog = path.join(tmp, 'aws.log');
const secLog = path.join(tmp, 'sec.log');
const npmLog = path.join(tmp, 'npm2.log');
function releaseStubs() {
    fs.rmSync(secLog, { force: true }); fs.rmSync(npmLog, { force: true }); fs.rmSync(awsLog, { force: true });
    stub('security', `echo "$*" >> "${secLog}"; case "$1" in show-keychain-info) echo "Keychain no-timeout" >&2;; find-identity) ${listing('')};; -i) cat >/dev/null; exit "\${SEC_I_RC:-0}";; esac; exit 0`);
    stub('aws', `echo "$*" >> "${awsLog}"; case "$*" in *asc-api-key*) echo '{"key_id":"K1","issuer_id":"I1","p8":"p8data"}';; *) printf '%s\\n' "$PW";; esac`);
    npmStub(`{ env | grep -E '^(CSC_|APPLE_|CARNIVORE_PAYLOAD_SIGN_)' | sed 's/=.*//' | sort; echo "ARGS $*"; } >> "${npmLog}"; out=dist; for a in "$@"; do case "$a" in -c.directories.output=*) out="\${a#*=}";; esac; done; if [ -n "$STUB_MANIFEST" ]; then mkdir -p "$out"; cp "$STUB_MANIFEST" "$out/latest-mac.yml"; grep -E '^ *- url:' "$out/latest-mac.yml" | sed 's/.*url: *//' | while read -r f; do echo x > "$out/$f"; done; fi`);
}
const dirty = { CSC_LINK: 'x', CSC_KEY_PASSWORD: 'x', CSC_NAME: 'x', CSC_IDENTITY_AUTO_DISCOVERY: 'false', APPLE_ID: 'x', APPLE_APP_SPECIFIC_PASSWORD: 'x', APPLE_TEAM_ID: 'x', APPLE_KEYCHAIN: 'x' };

const goodManifest = path.join(tmp, 'good-latest-mac.yml');
fs.writeFileSync(goodManifest, GOOD_MANIFEST);

test('release-build signed path: inherited CSC_/APPLE_ cleared, signing forced, keychain locked', () => {
    releaseStubs();
    const r = sh(releaseSh, [`-c.directories.output=${path.join(tmp, 'out-signed')}`], { ...dirty, PW: 'pw', STUB_MANIFEST: goodManifest });
    assert.equal(r.status, 0, r.stderr);
    const log = fs.readFileSync(npmLog, 'utf8');
    for (const v of Object.keys(dirty)) assert.doesNotMatch(log, new RegExp(`^${v}$`, 'm'), `${v} must not reach the build`);
    for (const v of ['CSC_KEYCHAIN', 'APPLE_API_KEY', 'APPLE_API_KEY_ID', 'APPLE_API_ISSUER']) assert.match(log, new RegExp(`^${v}$`, 'm'));
    assert.match(log, /ARGS run package -- -c\.mac\.identity=A{40} -c\.forceCodeSigning=true/);
    for (const v of ['CARNIVORE_PAYLOAD_SIGN_SHA1', 'CARNIVORE_PAYLOAD_SIGN_KEYCHAIN']) assert.match(log, new RegExp(`^${v}$`, 'm'), `${v} reaches the build`);
    const calls = fs.readFileSync(path.join(path.dirname(releaseSh), '..', 'payload', 'sign-payload.calls'), 'utf8');
    assert.match(calls, /^--verify-app .*Carnivore\.app$/m, 'the built app is verified through sign-payload.sh');
    const sec = fs.readFileSync(secLog, 'utf8');
    assert.doesNotMatch(sec, /set-keychain-settings/, 'no keychain setting is ever written');
    assert.match(sec, /lock-keychain /);
});

test('release-build ad hoc path: inherited CSC_/APPLE_ cleared too', () => {
    releaseStubs();
    stub('security', `case "$1" in show-keychain-info) echo "Keychain no-timeout" >&2;; find-identity) echo '  1) ${OTHER} "Developer ID Application: Alex Callen (MDH8UQ6H46)"';; -i) cat >/dev/null;; esac; exit 0`);
    const r = sh(releaseSh, [], { ...dirty, APPLE_API_KEY: 'x', PW: 'pw' });
    assert.equal(r.status, 0, r.stderr);
    assert.doesNotMatch(fs.readFileSync(npmLog, 'utf8'), /^(CSC_|APPLE_|CARNIVORE_PAYLOAD_SIGN_)/m);
});

test('release-build: a quote or backslash in the keychain password is refused, never printed', () => {
    for (const pw of ['p"w', 'p\\w']) {
        releaseStubs();
        const r = sh(releaseSh, [], { PW: pw });
        assert.notEqual(r.status, 0);
        assert.match(r.stderr, /quote or backslash/);
        assert.equal(r.stderr.includes(pw) || r.stdout.includes(pw), false, 'password must not be printed');
        assert.equal(fs.existsSync(npmLog), false, 'build must not run');
    }
});

test('release-build: the keychain is locked again when the unlock itself fails', () => {
    releaseStubs();
    const r = sh(releaseSh, [], { PW: 'pw', SEC_I_RC: '1' });
    assert.notEqual(r.status, 0);
    assert.match(fs.readFileSync(secLog, 'utf8'), /lock-keychain /);
    assert.equal(fs.existsSync(npmLog), false);
});

const policy = require(path.join(repo, 'macOS', 'scripts', 'electron-policy.js'));

test('R1-01 the real package.json: exact pins, universal on every target, floor 14.0, allowScripts moved with Electron', () => {
    const pins = PINNED.map((n) => specOf(realPkg, n));
    assert.equal(pins.length, 3, 'population check: three packages');
    for (const [i, spec] of pins.entries()) assert.match(String(spec), /^\d+\.\d+\.\d+$/, `${PINNED[i]} must be an exact version, got ${spec}`);
    const targets = realPkg.build.mac.target;
    assert.deepEqual(targets.map((t) => t.target).sort(), ['dmg', 'zip'], 'population check: dmg and zip');
    for (const t of targets) assert.deepEqual(t.arch, ['universal'], `${t.target} must be universal`);
    assert.equal(realPkg.build.mac.minimumSystemVersion, '14.0');
    assert.deepEqual(Object.keys(realPkg.allowScripts), [`electron@${pins[0]}`]);
});

test('R1-01 policy parts: newestStable skips prereleases; a range is not a pin', () => {
    const times = { created: '2020-01-01T00:00:00Z', '44.7.0': '2026-10-07T19:26:00Z', '44.9.3': '2026-10-21T03:31:00Z', '45.0.0': '2026-10-21T06:03:00Z', '46.0.0-beta.1': '2026-08-01T00:00:00Z', '43.9.0': '2026-09-01T00:00:00Z' };
    assert.equal(policy.newestStable(times), '45.0.0');
    assert.equal(policy.newestStable({ created: '2020-01-01T00:00:00Z', '46.0.0-beta.1': '2026-08-01T00:00:00Z' }), null);
    assert.throws(() => policy.parsePins({ devDependencies: { electron: '^44.7.0', 'electron-builder': '26.15.3' }, dependencies: { 'electron-updater': '6.8.9' } }), /electron is "\^44\.7\.0"/);
    assert.equal(Object.keys(policy.parsePins(realPkg)).length, 3, 'population check: the real pins parse to three packages');
});

function assertRefused(m, re, env = {}, args = []) {
    releaseStubs();
    const r = sh(m.releaseSh, args, { PW: 'pw', ...env });
    assert.notEqual(r.status, 0, `the build must be refused:\n${r.stderr}`);
    assert.match(r.stderr, re);
    assert.equal(fs.existsSync(npmLog), false, 'npm run package must not run');
    assert.equal(fs.existsSync(awsLog), false, 'no secret may be fetched');
    assert.equal(fs.existsSync(secLog), false, 'the keychain must not be touched');
    return r;
}
function assertBuilt(m, env = {}, args = []) {
    releaseStubs();
    const r = sh(m.releaseSh, args, { PW: 'pw', ...env });
    assert.equal(r.status, 0, r.stderr);
    assert.ok(fs.existsSync(npmLog), 'npm run package must run');
    return r;
}
const outArg = (name) => `-c.directories.output=${path.join(tmp, name)}`;

test('R1-01 release-build refuses an arm64-only target ("universal required")', () => {
    assertRefused(mirror((p) => { p.build.mac.target[1].arch = ['arm64']; }), /universal required/);
    assertRefused(mirror((p) => { p.build.mac.target.forEach((t) => { t.arch = ['arm64']; }); }), /universal required/);
});

test('R1-01 release-build refuses a floor other than 14.0', () => {
    assertRefused(mirror((p) => { p.build.mac.minimumSystemVersion = '13.0'; }), /minimumSystemVersion/);
    assertRefused(mirror((p) => { delete p.build.mac.minimumSystemVersion; }), /minimumSystemVersion/);
});

test('R1-01 release-build refuses a caret range, a tilde and a tag on each of the three packages', () => {
    for (const name of PINNED) {
        for (const prefix of ['^', '~', '>=']) {
            const m = mirror((p) => {
                const sect = p.dependencies?.[name] !== undefined ? p.dependencies : p.devDependencies;
                sect[name] = `${prefix}${sect[name]}`;
            });
            assertRefused(m, new RegExp(`${name} is "\\${prefix[0]}[^"]*" in macOS/package.json: pin an exact version`));
        }
    }
    assertRefused(mirror((p) => { p.devDependencies.electron = 'latest'; }), /electron is "latest"/);
});

test('R1-01 release-build refuses an installed version that differs from its pin, naming package, pin and installed', () => {
    for (const name of PINNED) {
        const r = assertRefused(mirror(() => {}, { [name]: '1.2.3' }), new RegExp(`${name} pinned ${String(specOf(realPkg, name)).replaceAll('.', '\\.')} but installed 1\\.2\\.3`));
        assert.match(r.stderr, /never installs/);
    }
    const missing = mirror();
    fs.rmSync(path.join(missing.mac, 'node_modules', 'electron-updater'), { recursive: true });
    assertRefused(missing, /electron-updater pinned .* but installed not installed/);
});

test('R1-01 release-build refuses a missing allowScripts key for the pinned Electron', () => {
    assertRefused(mirror((p) => { p.allowScripts = { 'electron@1.0.0': true }; }), /allowScripts has no "electron@/);
});

test('R1-01 release-build refuses a pin one version behind the newest stable (even a day old), and passes a pin published today', () => {
    const [maj, min, pat] = pinNow.split('.').map(Number);
    const newer = `${maj}.${min + 1}.${pat}`;
    assertRefused(baseMirror, new RegExp(`electron ${newer.replaceAll('.', '\\.')} is the newest stable and the pin is ${pinNow.replaceAll('.', '\\.')}: bump the pin`), { REGISTRY_FILE: registry(pinNow, 30, [[newer, 1]]) });
    assertBuilt(baseMirror, { REGISTRY_FILE: registry(pinNow, 0), STUB_MANIFEST: goodManifest }, [outArg('o-today')]);
});

test('R1-01 release-build refuses when the latest tag and the newest stable disagree, or the pin is not a listed release', () => {
    assertRefused(baseMirror, /newest stable electron is .* but its latest tag is 1\.0\.0/, { REGISTRY_FILE: registry(pinNow, 30, [], '1.0.0') });
    const ghost = path.join(tmp, 'ghost.json');
    fs.writeFileSync(ghost, JSON.stringify({ time: { created: '2020-01-01T00:00:00Z', '1.0.0': '2020-01-02T00:00:00Z' }, 'dist-tags': { latest: '1.0.0' } }));
    assertRefused(baseMirror, /is not on the registry's stable list/, { REGISTRY_FILE: ghost });
});

test('R1-01 release-build refuses when the registry cannot be read (never a pass)', () => {
    const junk = path.join(tmp, 'junk.json');
    fs.writeFileSync(junk, 'not json');
    assertRefused(baseMirror, /could not determine/, { REGISTRY_FILE: junk });
    assertRefused(baseMirror, /could not determine/, { REGISTRY_RC: '1' });
    const empty = path.join(tmp, 'empty.json');
    fs.writeFileSync(empty, '{"time":{"created":"2020-01-01T00:00:00Z"},"dist-tags":{"latest":"1.0.0"}}');
    assertRefused(baseMirror, /could not determine/, { REGISTRY_FILE: empty });
});

test('R1-01 the built manifest gets the update floor and names one universal zip', () => {
    const out = path.join(tmp, 'o-manifest');
    assertBuilt(baseMirror, { STUB_MANIFEST: goodManifest }, [`-c.directories.output=${out}`]);
    const yml = fs.readFileSync(path.join(out, 'latest-mac.yml'), 'utf8');
    assert.equal(yml.match(/^minimumSystemVersion: 23\.0\.0$/gm)?.length, 1, 'the floor is written once (Darwin 23 is macOS 14; see electron-policy.js)');
    assert.match(yml, /url: Carnivore-2\.0\.0-beta\.1-universal-mac\.zip/);
    fs.writeFileSync(path.join(out, 'latest-mac.yml'), yml.replace('23.0.0', '13.0.0'));
    assert.equal(policy.finish(path.join(baseMirror.mac), [`-c.directories.output=${out}`], {}, true).length, 1);
    assert.equal(fs.readFileSync(path.join(out, 'latest-mac.yml'), 'utf8').match(/^minimumSystemVersion: .*$/gm).join(), 'minimumSystemVersion: 23.0.0');
});

test('R1-01 a manifest naming an arm64 zip, two zips or no zip, or no manifest on a signed build, fails the build', () => {
    const bad = (name, body) => { const f = path.join(tmp, name); fs.writeFileSync(f, body); return f; };
    for (const [name, body] of [
        ['m-arm64.yml', manifestBody('Carnivore-2.0.0-beta.1-arm64-mac.zip')],
        ['m-two.yml', manifestBody('Carnivore-2.0.0-beta.1-universal-mac.zip', 'Carnivore-2.0.0-beta.1-x64-mac.zip')],
        ['m-none.yml', manifestBody('Carnivore-2.0.0-beta.1-universal.dmg')],
    ]) {
        releaseStubs();
        const r = sh(releaseSh, [outArg(`o-${name}`)], { PW: 'pw', STUB_MANIFEST: bad(name, body) });
        assert.notEqual(r.status, 0, `${name} must fail the build`);
        assert.match(r.stderr, /latest-mac\.yml must name exactly one universal zip/);
    }
    releaseStubs();
    const r = sh(releaseSh, [outArg('o-missing')], { PW: 'pw' });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /(the build wrote no .*|restamp-manifest: no )latest-mac\.yml/);
});


test('notarize-dmg: every notarytool --wait carries a timeout', () => {
    const xlog = path.join(tmp, 'xcrun.log');
    stub('xcrun', `echo "$*" >> "${xlog}"; [ "$1" = notarytool ] && echo '{"status":"Accepted","id":"S1"}'; exit 0`);
    const script = `require(${JSON.stringify(path.join(repo, 'macOS', 'scripts', 'notarize-dmg.js'))})({ artifactPaths: ['/x/a.dmg'], configuration: { mac: { identity: 'AA' } } }).catch((e) => { console.error(e.message); process.exit(1); })`;
    const r = spawnSync('node', ['-e', script], {
        encoding: 'utf8',
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, APPLE_API_KEY: 'k', APPLE_API_KEY_ID: 'i', APPLE_API_ISSUER: 'u' },
    });
    assert.equal(r.status, 0, r.stderr);
    assert.match(fs.readFileSync(xlog, 'utf8'), /notarytool submit .* --wait --timeout 30m /);
});

test('entitlements: exactly allow-jit and automation.apple-events', () => {
    const json = execFileSync('plutil', ['-convert', 'json', '-o', '-', path.join(repo, 'macOS', 'scripts', 'entitlements.mac.plist')], { encoding: 'utf8' });
    assert.deepEqual(JSON.parse(json), { 'com.apple.security.cs.allow-jit': true, 'com.apple.security.automation.apple-events': true });
});

test('notarize-dmg: a build with mac.identity null never submits, even with APPLE_API_* set', () => {
    const xlog = path.join(tmp, 'xcrun-adhoc.log');
    stub('xcrun', `echo "$*" >> "${xlog}"; exit 0`);
    const script = `require(${JSON.stringify(path.join(repo, 'macOS', 'scripts', 'notarize-dmg.js'))})({ artifactPaths: ['/x/a.dmg'], configuration: { mac: { identity: null } } }).catch((e) => { console.error(e.message); process.exit(1); })`;
    const r = spawnSync('node', ['-e', script], {
        encoding: 'utf8',
        env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, APPLE_API_KEY: 'k', APPLE_API_KEY_ID: 'i', APPLE_API_ISSUER: 'u' },
    });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(fs.existsSync(xlog), false, 'xcrun must not run');
});

test('entitlementsInherit: nested helpers get allow-jit alone', () => {
    const pkg = JSON.parse(fs.readFileSync(path.join(repo, 'macOS', 'package.json'), 'utf8'));
    assert.equal(pkg.build.mac.entitlementsInherit, 'scripts/entitlements.mac.inherit.plist');
    const json = execFileSync('plutil', ['-convert', 'json', '-o', '-', path.join(repo, 'macOS', pkg.build.mac.entitlementsInherit)], { encoding: 'utf8' });
    assert.deepEqual(JSON.parse(json), { 'com.apple.security.cs.allow-jit': true });
});

test('import: the unlocked flag is set before the unlock, no keychain setting is written, bundle imported with -x', () => {
    const lib = fs.readFileSync(path.join(repo, 'macOS', 'scripts', 'signing-keychain-session.sh'), 'utf8');
    assert.ok(lib.indexOf('KCS_UNLOCKED=1\n') < lib.indexOf('unlock-keychain -p'), 'flag before unlock');
    const code = lib.replace(/^\s*#.*$/gm, '');
    const outside = code.replace(/kcs_set_never_autolock\(\) \{[^]*?\n\}\n/, '');
    assert.match(code, /set-keychain-settings \\"\$keychain\\"/, 'population check: the one setting call exists');
    assert.doesNotMatch(fs.readFileSync(importSh, 'utf8').replace(/^\s*#.*$/gm, '') + outside, /\bset-keychain-settings\b(?!\))/);
    assert.match(fs.readFileSync(importSh, 'utf8'), /-P \\"\$pass\\" -x -T \/usr\/bin\/codesign/);
});

if (realKeychainTests) {
    test('import on a REAL scratch keychain: the RSA key is found by its real application label', () => {
        const home = path.join(tmp, 'realhome');
        const kc = path.join(home, 'Library', 'Keychains', 'carnivore-signing.keychain-db');
        fs.mkdirSync(path.dirname(kc), { recursive: true });
        const sec = (args) => spawnSync('/usr/bin/security', args, { encoding: 'utf8' });
        assert.equal(sec(['create-keychain', '-p', 'pw', kc]).status, 0);
        try {
            stub('security', `${fakeListPrefix()}exec /usr/bin/security "$@"`);
            awsStub(); stub('codesign', 'exit 0'); stub('node', `printf '%s\\n' ${'B'.repeat(40)}`);
            const k = path.join(tmp, 'real.key');
            fs.copyFileSync(mine.key, k); fs.chmodSync(k, 0o600);
            const r = sh(importSh, [mine.cert], { HOME: home, CARNIVORE_DEVID_KEY: k, BACKUP_KEY: mine.key });
            assert.equal(r.status, 0, r.stderr);
            assert.doesNotMatch(r.stderr, /was not found/);
            assert.equal(fs.existsSync(k), false);
        } finally {
            sec(['delete-keychain', kc]);
        }
    });
}

if (realKeychainTests) {
    test('import on a REAL keychain that already holds a PEM "Imported Private Key": the bundle key gets its own label', () => {
        const home = path.join(tmp, 'colhome');
        const kc = path.join(home, 'Library', 'Keychains', 'carnivore-signing.keychain-db');
        fs.mkdirSync(path.dirname(kc), { recursive: true });
        const real = '/usr/bin/security';
        const sec = (args) => spawnSync(real, args, { encoding: 'utf8' });
        const labels = (out) => [...out.matchAll(/^ +0x00000001 <blob>="(.*)"$/gm)].map((m) => m[1]);
        const argvLog = path.join(tmp, 'col-argv.log');
        const stdinLog = path.join(tmp, 'col-stdin.log');
        const outLog = path.join(tmp, 'col-out.log');
        assert.equal(sec(['create-keychain', '-p', 'pw', kc]).status, 0);
        try {
            assert.equal(sec(['unlock-keychain', '-p', 'pw', kc]).status, 0);
            assert.equal(sec(['import', other.key, '-k', kc]).status, 0);
            assert.deepEqual(labels(sec(['dump-keychain', kc]).stdout).filter((l) => l === 'Imported Private Key'), ['Imported Private Key']);
            stub('security', `${fakeListPrefix()}echo "$*" >> "${argvLog}"; if [ "$1" = -i ]; then tee -a "${stdinLog}" | ${real} -i | tee -a "${outLog}"; else exec ${real} "$@"; fi`);
            awsStub(); stub('codesign', 'exit 0'); stub('node', `printf '%s\\n' ${'B'.repeat(40)}`);
            const k = path.join(tmp, 'col.key');
            fs.copyFileSync(mine.key, k); fs.chmodSync(k, 0o600);
            const r = sh(importSh, [mine.cert], { HOME: home, CARNIVORE_DEVID_KEY: k, BACKUP_KEY: mine.key });
            assert.equal(r.status, 0, r.stderr);
            assert.equal(fs.existsSync(k), false, 'key file deleted after verification');
            const friendly = 'Carnivore Developer ID Nyedis ARD6KN4BX4';
            assert.deepEqual(labels(sec(['dump-keychain', kc]).stdout).filter((l) => l.startsWith('Carnivore') || l === 'Imported Private Key').sort(), [friendly, 'Imported Private Key']);
            const stdin = fs.readFileSync(stdinLog, 'utf8');
            assert.match(stdin, new RegExp(`set-key-partition-list .* -l "${friendly}" -k`), 'partition list targeted the new key by its label');
            assert.doesNotMatch(stdin, /-l "Imported Private Key"/);
            assert.deepEqual(labels(fs.readFileSync(outLog, 'utf8')), [friendly], 'only the new key was rewritten');
            const ident = sec(['find-identity', kc]).stdout;
            assert.match(ident, /Developer ID Application: Nyedis \(ARD6KN4BX4\)/, 'the stand-in identity is listed');
            const pass = stdin.match(/import ".*" -k ".*" -P "([0-9a-f]+)"/)?.[1];
            assert.ok(pass && pass.length >= 32, 'the import command carried a random passphrase on stdin');
            assert.equal(fs.readFileSync(argvLog, 'utf8').includes(pass), false, 'passphrase never on argv');
            assert.doesNotMatch(r.stderr + r.stdout, new RegExp(pass), 'passphrase never printed');
            assert.deepEqual(fs.readdirSync(tmp).filter((f) => f.startsWith('carnivore-devid.')), [], 'scratch dir removed');
        } finally {
            sec(['delete-keychain', kc]);
        }
    });
}

const repoRoot = path.join(here, '..', '..');
const macDir = path.join(repoRoot, 'macOS');
const { PAYLOAD_SIGN_IGNORE } = require(path.join(macDir, 'scripts', 'signing-config.js'));
const signPayloadSh = path.join(macDir, 'payload', 'sign-payload.sh');
const payloadPlist = path.join(macDir, 'payload', 'entitlements.payload.plist');
const signingInputs = [
    path.join(macDir, 'payload', 'sign-payload.sh'),
    path.join(macDir, 'payload', 'entitlements.payload.plist'),
    path.join(macDir, 'scripts', 'signing-config.js'),
    path.join(macDir, 'scripts', 'release-build.sh'),
    path.join(macDir, 'scripts', 'after-pack.js'),
    path.join(macDir, 'scripts', 'payload-after-pack.js'),
    path.join(macDir, 'scripts', 'entitlements.mac.plist'),
    path.join(macDir, 'scripts', 'entitlements.mac.inherit.plist'),
    path.join(macDir, 'package.json'),
];

function payloadSigningViolations(text) {
    const found = [];
    if (/--deep\b/.test(text)) found.push('--deep');
    if (/disable-library-validation/.test(text)) found.push('disable-library-validation');
    return found;
}

test('payload entitlements plist parses to an empty dict', () => {
    const json = execFileSync('plutil', ['-convert', 'json', '-o', '-', payloadPlist], { encoding: 'utf8' });
    assert.deepEqual(JSON.parse(json), {});
});

test('no signing input has a deep signing flag or relaxes library validation (red on a seeded violation)', () => {
    assert.deepEqual(payloadSigningViolations('codesign --force --deep --sign x app'), ['--deep']);
    assert.deepEqual(payloadSigningViolations('<key>com.apple.security.cs.disable-library-validation</key>'), ['disable-library-validation']);
    for (const f of signingInputs) {
        assert.ok(fs.existsSync(f), `population check: ${f} exists`);
        const text = f.endsWith('.plist')
            ? Object.keys(JSON.parse(execFileSync('plutil', ['-convert', 'json', '-o', '-', f], { encoding: 'utf8' }))).join('\n')
            : fs.readFileSync(f, 'utf8');
        assert.deepEqual(payloadSigningViolations(text), [], f);
    }
});

test('electron-builder skips the payload folder, so app entitlements never reach a payload path', () => {
    const mac = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8')).build.mac;
    assert.deepEqual(mac.signIgnore, [PAYLOAD_SIGN_IGNORE], 'package.json signIgnore is exactly the signing-config constant');
    const re = new RegExp(PAYLOAD_SIGN_IGNORE);
    const app = '/x/dist/mac-universal/Carnivore.app';
    assert.ok(re.test(`${app}/Contents/Resources/payload/payload-arm64/python/bin/python3.12`));
    assert.ok(re.test(`${app}/Contents/Resources/payload/payload-x86_64/bin/tmux`));
    assert.ok(!re.test(`${app}/Contents/MacOS/Carnivore`));
    assert.ok(!re.test(`${app}/Contents/Frameworks/Electron Framework.framework/Electron Framework`));
    const script = fs.readFileSync(signPayloadSh, 'utf8');
    assert.match(script, /entitlements\.payload\.plist/);
    assert.doesNotMatch(script, /entitlements\.mac/);
    assert.ok(!mac.entitlements.includes('payload') && !mac.entitlementsInherit.includes('payload'));
});

if (process.platform === 'darwin') test('sign-payload.sh signs inside out, hardened, python-like executables with zero entitlements', () => {
    const work = fs.mkdtempSync(path.join(tmp, 'payload-'));
    const tree = path.join(work, 'payload-arm64');
    fs.mkdirSync(path.join(tree, 'python', 'bin'), { recursive: true });
    fs.mkdirSync(path.join(tree, 'python', 'lib', 'site-packages', 'pkg', 'sub'), { recursive: true });
    fs.mkdirSync(path.join(tree, 'bin'), { recursive: true });
    const build = (kind, out) => {
        const flags = { exe: [], dylib: ['-dynamiclib'], so: ['-bundle', '-undefined', 'dynamic_lookup'] }[kind];
        execFileSync('cc', [...flags, '-x', 'c', '-', '-o', out], { input: kind === 'exe' ? 'int main(void){return 0;}' : 'int f(void){return 1;}' });
    };
    build('exe', path.join(tree, 'python', 'bin', 'python3.12'));
    build('exe', path.join(tree, 'bin', 'tmux'));
    build('dylib', path.join(tree, 'python', 'lib', 'libpython3.12.dylib'));
    build('so', path.join(tree, 'python', 'lib', 'site-packages', 'pkg', 'sub', 'deep.so'));
    build('so', path.join(tree, 'python', 'lib', 'site-packages', 'pkg', 'top.so'));
    fs.chmodSync(path.join(tree, 'python', 'lib', 'site-packages', 'pkg', 'top.so'), 0o755);
    const r = spawnSync('bash', [signPayloadSh, tree, '--identity', '-'], { encoding: 'utf8' });
    assert.equal(r.status, 0, r.stderr);
    const signed = r.stdout.split('\n').filter((l) => l.startsWith('signed ')).map((l) => l.slice(7));
    assert.equal(signed.length, 5, 'population check: all five Mach-O files were signed');
    const depth = (f) => f.split(path.sep).length;
    assert.deepEqual([...signed].sort((a, b) => depth(b) - depth(a)).map(depth), signed.map(depth), 'deepest path signed first');
    for (const f of signed) {
        const details = spawnSync('codesign', ['-dv', '--verbose=4', f], { encoding: 'utf8' });
        assert.match(details.stderr, /flags=0x[0-9a-f]+\([^)]*runtime/, `hardened runtime on ${f}`);
        const ents = spawnSync('codesign', ['-d', '--entitlements', '-', '--xml', f], { encoding: 'utf8' });
        assert.equal(ents.status, 0, `codesign answered for ${f}`);
        const keys = ents.stdout.trim() ? Object.keys(JSON.parse(execFileSync('plutil', ['-convert', 'json', '-o', '-', '-'], { input: ents.stdout, encoding: 'utf8' }))) : [];
        assert.deepEqual(keys, [], `no entitlement keys on ${f}`);
        assert.equal(spawnSync('codesign', ['--verify', '--strict', f]).status, 0, `strict verify ${f}`);
    }
    const { buildManifest, lockWheels } = require(path.join(macDir, 'scripts', 'payload-manifest.js'));
    fs.cpSync(tree, path.join(work, 'payload-x86_64'), { recursive: true });
    const m = buildManifest(work);
    const sha = (f) => execFileSync('shasum', ['-a', '256', f], { encoding: 'utf8' }).split(' ')[0];
    assert.equal(m.trees.arm64.binaries.length, 5);
    for (const b of m.trees.arm64.binaries) assert.equal(b.sha256, sha(path.join(tree, b.path)), b.path);
    for (const arch of ['arm64', 'x86_64']) {
        const names = m.trees[arch].components.map((c) => c.name);
        assert.deepEqual(names, ['python', 'tmux']);
        for (const c of m.trees[arch].components) {
            assert.match(c.url, /^https:\/\//);
            assert.match(c.sha256, /^[0-9a-f]{64}$/);
            assert.match(c.version, /^\d+\.\d+/);
        }
    }
    assert.ok(m.wheels.length > 10 && m.wheels.every((w) => w.version && w.sha256.length > 0), 'lock wheels parsed with hashes');
    assert.ok(m.wheels.some((w) => w.name === 'fastapi'));
    assert.deepEqual(lockWheels('a==1.0 \\\n    --hash=sha256:' + 'ab'.repeat(32) + '\n'), [{ name: 'a', version: '1.0', source: 'pypi', sha256: ['ab'.repeat(32)] }]);
});

const pbin = path.join(tmp, 'pstub');
fs.mkdirSync(pbin, { recursive: true });
const GOOD_DETAILS = 'Executable=x\nFormat=Mach-O\nCodeDirectory v=20500 size=1 flags=0x10000(runtime) hashes=1+0 location=embedded\nTimestamp=Oct 23, 2026 at 10:00:00\nTeamIdentifier=ARD6KN4BX4\n';
fs.writeFileSync(path.join(pbin, 'codesign'), `#!/bin/bash
case " $* " in
  *" --entitlements - --xml "*) [ -n "$CS_ENT_FAIL" ] && exit 1; [ -n "$CS_ENT_XML" ] && cat "$CS_ENT_XML"; exit 0 ;;
  *" -dvv "*) cat "$CS_DETAILS" >&2; exit 0 ;;
  *" -R="*) [ -n "$CS_NO_TEAM" ] && exit 1; exit 0 ;;
  *" --verify "*) exit 0 ;;
  *" --sign "*)
    echo "SIGN $*" >> "$CS_LOG"
    prev=""; for a in "$@"; do [ "$prev" = "--entitlements" ] && { echo "ENTFILE $(tr -d '\\n ' < "$a")" >> "$CS_LOG"; }; prev="$a"; done
    exit 0 ;;
esac
exit 0
`, { mode: 0o755 });
fs.writeFileSync(path.join(pbin, 'spctl'), '#!/bin/bash\nexit 0\n', { mode: 0o755 });
const pstubEnv = (extra = {}) => ({ ...process.env, PATH: `${pbin}:${process.env.PATH}`, CS_LOG: path.join(tmp, 'cs.log'), CS_DETAILS: path.join(tmp, 'cs.details'), ...extra });
fs.writeFileSync(path.join(tmp, 'cs.details'), GOOD_DETAILS);
const ENTITLED_XML = path.join(tmp, 'entitled.xml');
fs.writeFileSync(ENTITLED_XML, '<?xml version="1.0"?><plist version="1.0"><dict><key>com.apple.security.cs.disable-library-validation</key><true/></dict></plist>');

function signLogViolations(log) {
    const found = [];
    if (/disable-library-validation|allow-dyld-environment-variables/.test(log)) found.push('relaxation');
    for (const m of log.matchAll(/^ENTFILE (.*)$/gm)) if (!/^<\?xml.*<plist[^>]*><dict(\/>|><\/dict>)<\/plist>$/.test(m[1])) found.push('non-empty plist');
    if (/--deep\b/.test(log)) found.push('--deep');
    return found;
}

function thinExe(out) {
    fs.mkdirSync(path.dirname(out), { recursive: true });
    execFileSync('cc', ['-x', 'c', '-', '-o', out], { input: 'int main(void){return 0;}' });
}
function fatOf(thin, out, wide) {
    const body = fs.readFileSync(thin);
    const off = 0x4000;
    const head = Buffer.alloc(8 + (wide ? 32 : 20));
    head.writeUInt32BE(wide ? 0xcafebabf : 0xcafebabe, 0);
    head.writeUInt32BE(1, 4);
    head.writeUInt32BE(0x0100000c, 8);
    if (wide) { head.writeBigUInt64BE(BigInt(off), 16); head.writeBigUInt64BE(BigInt(body.length), 24); }
    else { head.writeUInt32BE(off, 16); head.writeUInt32BE(body.length, 20); }
    fs.writeFileSync(out, Buffer.concat([head, Buffer.alloc(off - head.length), body]), { mode: 0o755 });
}
function fakeApp(name, make) {
    const app = path.join(tmp, `${name}.app`);
    make(path.join(app, 'Contents', 'Resources', 'payload', 'payload-arm64', 'bin', 'tmux'));
    return app;
}
const verifyApp = (app, extra = {}) => spawnSync('bash', [signPayloadSh, '--verify-app', app], { encoding: 'utf8', env: pstubEnv(extra) });

if (process.platform === 'darwin') {
    test('signLogViolations is red on the review seeded edit (a runtime plist with the relaxation keys)', () => {
        const seeded = 'SIGN --sign X\nENTFILE <?xml?><plist><dict><key>com.apple.security.cs.disable-library-validation</key><true/></dict></plist>\n';
        assert.deepEqual(signLogViolations(seeded), ['relaxation', 'non-empty plist']);
        assert.deepEqual(signLogViolations('SIGN --sign X\nENTFILE <?xmlversion="1.0"?><plist version="1.0"><dict/></plist>\n'), []);
    });

    test('Developer ID branch: every file hardened and timestamped in the keychain, executables get only the empty plist', () => {
        const tree = path.join(tmp, 'devid', 'payload-arm64');
        thinExe(path.join(tree, 'bin', 'tmux'));
        execFileSync('cc', ['-dynamiclib', '-x', 'c', '-', '-o', path.join(tree, 'lib.dylib')], { input: 'int f(void){return 1;}' });
        const kc = path.join(tmp, 'fake.keychain-db');
        fs.writeFileSync(kc, 'x');
        fs.rmSync(path.join(tmp, 'cs.log'), { force: true });
        const r = spawnSync('bash', [signPayloadSh, tree, '--identity', 'A'.repeat(40), '--keychain', kc], { encoding: 'utf8', env: pstubEnv() });
        assert.equal(r.status, 0, r.stderr);
        const log = fs.readFileSync(path.join(tmp, 'cs.log'), 'utf8');
        const signs = log.split('\n').filter((l) => l.startsWith('SIGN '));
        assert.equal(signs.length, 2, 'population check: both files signed');
        for (const l of signs) assert.match(l, /--options runtime --sign A{40} --timestamp --keychain /);
        assert.equal(log.split('\n').filter((l) => l.startsWith('ENTFILE ')).length, 1, 'only the executable names an entitlements file');
        assert.deepEqual(signLogViolations(log), []);
    });

    test('Developer ID branch is red when a signed file lacks the runtime flag, a timestamp or the team', () => {
        const tree = path.join(tmp, 'devid2', 'payload-arm64');
        thinExe(path.join(tree, 'bin', 'tmux'));
        const kc = path.join(tmp, 'fake.keychain-db');
        const run = (extra) => spawnSync('bash', [signPayloadSh, tree, '--identity', 'A'.repeat(40), '--keychain', kc], { encoding: 'utf8', env: pstubEnv(extra) });
        const noRuntime = path.join(tmp, 'd-noruntime');
        fs.writeFileSync(noRuntime, GOOD_DETAILS.replace('(runtime)', '(none)'));
        const noStamp = path.join(tmp, 'd-nostamp');
        fs.writeFileSync(noStamp, GOOD_DETAILS.replace(/Timestamp=.*\n/, ''));
        assert.match(run({ CS_DETAILS: noRuntime }).stderr, /hardened runtime is off/);
        assert.match(run({ CS_DETAILS: noStamp }).stderr, /no secure timestamp/);
        assert.match(run({ CS_NO_TEAM: '1' }).stderr, /not signed by team ARD6KN4BX4/);
        assert.equal(run({}).status, 0, 'the same tree passes with good details');
    });

    test('--verify-app is red on an entitled executable, and on a codesign that cannot answer (never fails open)', () => {
        const app = fakeApp('v-thin', (f) => thinExe(f));
        assert.equal(verifyApp(app).status, 0, verifyApp(app).stderr);
        const bad = verifyApp(app, { CS_ENT_XML: ENTITLED_XML });
        assert.notEqual(bad.status, 0);
        assert.match(bad.stderr, /executable carries entitlements/);
        const dead = verifyApp(app, { CS_ENT_FAIL: '1' });
        assert.notEqual(dead.status, 0);
        assert.match(dead.stderr, /could not read the entitlements/);
    });

    test('--verify-app is red when a payload file is not Developer ID, not hardened or not timestamped', () => {
        const app = fakeApp('v-flags', (f) => thinExe(f));
        const noRuntime = path.join(tmp, 'v-noruntime');
        fs.writeFileSync(noRuntime, GOOD_DETAILS.replace('(runtime)', '(none)'));
        const noStamp = path.join(tmp, 'v-nostamp');
        fs.writeFileSync(noStamp, GOOD_DETAILS.replace(/Timestamp=.*\n/, ''));
        assert.match(verifyApp(app, { CS_NO_TEAM: '1' }).stderr, /not signed by team/);
        assert.match(verifyApp(app, { CS_DETAILS: noRuntime }).stderr, /hardened runtime is off/);
        assert.match(verifyApp(app, { CS_DETAILS: noStamp }).stderr, /no secure timestamp/);
    });

    test('a fat executable (32 or 64 bit header) gets the entitlement check; a fat-looking non-Mach-O is not a payload file', () => {
        const thin = path.join(tmp, 'thin-src');
        thinExe(thin);
        for (const wide of [false, true]) {
            const app = fakeApp(`v-fat${wide ? '64' : '32'}`, (f) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fatOf(thin, f, wide); });
            assert.equal(verifyApp(app).status, 0, verifyApp(app).stderr);
            const bad = verifyApp(app, { CS_ENT_XML: ENTITLED_XML });
            assert.notEqual(bad.status, 0, `fat${wide ? '64' : '32'} executable with an entitlement must fail`);
            assert.match(bad.stderr, /executable carries entitlements/);
        }
        const cls = fakeApp('v-class', (f) => { fs.mkdirSync(path.dirname(f), { recursive: true }); fs.writeFileSync(f, Buffer.from('cafebabe0000003400000000000000000000000000000000', 'hex')); });
        assert.match(verifyApp(cls).stderr, /no Mach-O files/);
        const { machoHashes } = require(path.join(macDir, 'scripts', 'payload-manifest.js'));
        const fat64 = path.join(tmp, 'v-fat64.app', 'Contents', 'Resources', 'payload', 'payload-arm64');
        assert.ok(machoHashes(fat64).some((r) => r.path === path.join('bin', 'tmux')), 'the manifest lists a fat64 file too');
    });
}

test('signPayload throws when an identity signs the app but the payload env is absent; an ad hoc build skips', () => {
    const saved = [process.env.CARNIVORE_PAYLOAD_SIGN_SHA1, process.env.CARNIVORE_PAYLOAD_SIGN_KEYCHAIN];
    delete process.env.CARNIVORE_PAYLOAD_SIGN_SHA1; delete process.env.CARNIVORE_PAYLOAD_SIGN_KEYCHAIN;
    try {
        const { signPayload } = require(path.join(macDir, 'scripts', 'payload-after-pack.js'));
        assert.equal(signPayload('/nonexistent.app', false), false);
        assert.throws(() => signPayload('/nonexistent.app', true), /payload would ship unsigned/);
    } finally {
        if (saved[0] !== undefined) process.env.CARNIVORE_PAYLOAD_SIGN_SHA1 = saved[0];
        if (saved[1] !== undefined) process.env.CARNIVORE_PAYLOAD_SIGN_KEYCHAIN = saved[1];
    }
});

test('release-build refuses CARNIVORE_SKIP_PAYLOAD=1 before any secret, keychain or build step', () => {
    assertRefused(baseMirror, /CARNIVORE_SKIP_PAYLOAD/, { CARNIVORE_SKIP_PAYLOAD: '1' });
});

test('release-build verifies the app this run built (mac-universal), not a stale app that find reaches first', () => {
    releaseStubs();
    const out = path.join(tmp, 'out-stale');
    fs.rmSync(out, { recursive: true, force: true });
    fs.mkdirSync(path.join(out, 'mac', 'Carnivore.app'), { recursive: true });
    fs.rmSync(path.join(path.dirname(releaseSh), '..', 'payload', 'sign-payload.calls'), { force: true });
    const r = sh(releaseSh, [`-c.directories.output=${out}`], { PW: 'pw', STUB_MANIFEST: goodManifest });
    assert.equal(r.status, 0, r.stderr);
    const calls = fs.readFileSync(path.join(path.dirname(releaseSh), '..', 'payload', 'sign-payload.calls'), 'utf8').trim().split('\n');
    assert.deepEqual(calls.map((c) => c.replace(/^--verify-app /, '')), [path.join(out, 'mac-universal', 'Carnivore.app')]);
});

fs.rmSync(tmp, { recursive: true, force: true });

if (failures > 0) {
    console.log(`${failures} failed`);
    process.exit(1);
}
console.log('all passed');
