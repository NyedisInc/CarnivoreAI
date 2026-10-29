
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';
import os from 'node:os';
import { spawnSync } from 'node:child_process';
import {
    mirror, registry, specOf, HARDENED_WIRE, STOCK_WIRE, ARM64, X86_64, sliceBytes, fatBinary, writeFakeBuilt, universal,
} from './lib/release_mirror.mjs';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(here, '..', '..');
const macDir = path.join(repo, 'macOS');
const realPkg = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8'));
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'hardening-test-'));
process.on('exit', () => fs.rmSync(tmp, { recursive: true, force: true }));

let failures = 0;
/** Run one named case, count a failure instead of aborting the rest. */
const pending = [];
function test(name, fn) {
    const report = (err) => {
        failures += 1;
        console.log(`FAIL ${name}\n     ${err.message.split('\n').slice(0, 6).join('\n     ')}`);
    };
    try {
        const result = fn();
        if (result && typeof result.then === 'function') {
            pending.push(result.then(() => console.log(`ok   ${name}`), report));
            return;
        }
        console.log(`ok   ${name}`);
    } catch (err) {
        report(err);
    }
}

const FUSES = {
    runAsNode: false,
    enableCookieEncryption: true,
    enableNodeOptionsEnvironmentVariable: false,
    enableNodeCliInspectArguments: false,
    enableEmbeddedAsarIntegrityValidation: true,
    onlyLoadAppFromAsar: true,
    loadBrowserProcessSpecificV8Snapshot: false,
    grantFileProtocolExtraPrivileges: false,
};

test('package.json build.electronFuses is exactly the eight pinned fuses', () => {
    assert.deepEqual(realPkg.build.electronFuses, FUSES);
    assert.equal(Object.keys(FUSES).length, 8, 'population check');
});

const BANNED = /\b(webviewTag|nodeIntegrationInWorker|enableRemoteModule|nodeIntegrationInSubFrames)\b/;
const SKIP_DIRS = new Set(['node_modules', 'scripts', 'payload', 'e2e']);

function shellSources(dir = macDir) {
    const out = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        if (entry.isDirectory()) {
            if (SKIP_DIRS.has(entry.name) || entry.name.startsWith('dist')) continue;
            out.push(...shellSources(path.join(dir, entry.name)));
        } else if (entry.name.endsWith('.js')) out.push(path.join(dir, entry.name));
    }
    return out;
}

/** The text between the brace at `open` and its match (exclusive), or null when unbalanced. */
function balanced(text, open) {
    let depth = 0;
    for (let i = open; i < text.length; i++) {
        if (text[i] === '{') depth += 1;
        else if (text[i] === '}' && --depth === 0) return text.slice(open + 1, i);
    }
    return null;
}

function auditWindows(source, label) {
    const sites = [];
    const re = /new\s+(?:deps\.)?(BrowserWindow|BrowserView|WebContentsView)\s*\(\s*(\{|[A-Za-z_$][\w$]*)/g;
    for (const m of source.matchAll(re)) {
        const problems = [];
        let options;
        if (m[2] === '{') options = balanced(source, m.index + m[0].length - 1);
        else {
            const decl = new RegExp(`(?:const|let|var)\\s+${m[2].replace('$', '\\$')}\\s*=\\s*\\{`).exec(source);
            options = decl ? balanced(source, decl.index + decl[0].length - 1) : null;
        }
        const wp = options === null ? null : /webPreferences\s*:\s*\{/.exec(options);
        const prefs = wp ? balanced(options, wp.index + wp[0].length - 1) : null;
        if (prefs === null) problems.push('no webPreferences object');
        else {
            if (!/\bcontextIsolation\s*:\s*true\b/.test(prefs)) problems.push('contextIsolation is not true');
            if (!/\bsandbox\s*:\s*true\b/.test(prefs)) problems.push('sandbox is not true');
            if (!/\bnodeIntegration\s*:\s*false\b/.test(prefs)) problems.push('nodeIntegration is not false');
            if (BANNED.test(prefs)) problems.push('a banned web preference');
        }
        sites.push({ site: `${label}:${source.slice(0, m.index).split('\n').length}`, kind: m[1], problems });
    }
    return sites;
}

test('every window options object has contextIsolation, sandbox and nodeIntegration set safely', () => {
    const sites = shellSources().flatMap((f) => auditWindows(fs.readFileSync(f, 'utf8'), path.relative(repo, f)));
    assert.ok(sites.length >= 6, `population check: expected at least 6 window sites, found ${sites.length}`);
    assert.deepEqual(sites.filter((s) => s.problems.length > 0), []);
    assert.deepEqual(sites.filter((s) => s.kind !== 'BrowserWindow'), [], 'no BrowserView or WebContentsView exists today');
});

test('no web preference that widens a renderer appears anywhere in the shell', () => {
    const files = shellSources();
    assert.ok(files.length >= 30, `population check: ${files.length} files`);
    const hits = files.filter((f) => BANNED.test(fs.readFileSync(f, 'utf8'))).map((f) => path.relative(repo, f));
    assert.deepEqual(hits, []);
});

test('the window audit goes red on a fixture: sandbox false, no webPreferences, an identifier with none, nothing found', () => {
    const bad = `const win = new BrowserWindow({ width: 1, webPreferences: { contextIsolation: true, sandbox: false, nodeIntegration: false } });`;
    assert.match(auditWindows(bad, 'f')[0].problems.join(), /sandbox is not true/);
    assert.match(auditWindows('new BrowserWindow({ width: 1 })', 'f')[0].problems.join(), /no webPreferences/);
    assert.match(auditWindows('const options = { width: 1 };\nnew BrowserWindow(options);', 'f')[0].problems.join(), /no webPreferences/);
    assert.match(auditWindows('new deps.BrowserWindow({ webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false, webviewTag: true } })', 'f')[0].problems.join(), /banned/);
    const good = 'const options = { webPreferences: { contextIsolation: true, sandbox: true, nodeIntegration: false } };\nnew BrowserWindow(options);';
    assert.deepEqual(auditWindows(good, 'f')[0].problems, []);
    assert.deepEqual(auditWindows('nothing here', 'f'), [], 'a source with no window finds no sites (so the >= 6 count above is a real check)');
});

test('macOS/preload.js is gone and nothing names it', () => {
    assert.equal(fs.existsSync(path.join(macDir, 'preload.js')), false);
    const stale = shellSources().filter((f) => /(?<![\w-])preload\.js\b/.test(fs.readFileSync(f, 'utf8'))).map((f) => path.relative(repo, f));
    assert.deepEqual(stale, []);
    assert.doesNotMatch(fs.readFileSync(path.join(macDir, 'README.md'), 'utf8'), /(?<![\w-])preload\.js\b/);
    assert.ok(fs.existsSync(path.join(macDir, 'app-window-preload.js')), 'population check: the live preload is still there');
});

test('the server-down status page needs no file-protocol privilege: no fetch, XHR, module, worker or storage', () => {
    const dir = path.join(macDir, 'status-window');
    const files = fs.readdirSync(dir).filter((f) => /\.(html|js|css)$/.test(f));
    assert.ok(files.length >= 3, `population check: ${files.join()}`);
    const lost = /\bfetch\s*\(|XMLHttpRequest|type\s*=\s*["']module["']|\bimport\s*\(|^\s*import\s|serviceWorker|new\s+Worker|localStorage|sessionStorage|indexedDB|pushState|@import|url\(\s*["']?file:/m;
    const hits = files.filter((f) => lost.test(fs.readFileSync(path.join(dir, f), 'utf8')));
    assert.deepEqual(hits, []);
    for (const f of ['status-window.js', 'update-window.js']) {
        const src = fs.readFileSync(path.join(macDir, f), 'utf8');
        assert.match(src, /loadURL\(serveLocalPage\(/, `${f} is served by its own session (#2477)`);
        assert.doesNotMatch(src, /loadFile\(/, `${f}: with the fuse off a file:// page inside app.asar is ERR_FILE_NOT_FOUND`);
    }
    assert.equal(lost.test('fetch("file:///x")'), true, 'the pattern goes red on a fetch');
    assert.equal(lost.test('<script type="module" src="a.js">'), true, 'and on a module script');
});

test('adhoc-sign: the per-architecture halves of a universal build are left unsigned (the merge refuses signed halves)', async () => {
    const hook = require(path.join(macDir, 'scripts', 'adhoc-sign.js'));
    const context = (dir) => ({ electronPlatformName: 'darwin', appOutDir: dir, packager: { appInfo: { productFilename: 'Carnivore' }, platformSpecificBuildOptions: { identity: null } } });
    for (const half of ['mac-universal-x64-temp', 'mac-universal-arm64-temp']) {
        const dir = path.join(tmp, half);
        fs.mkdirSync(path.join(dir, 'Carnivore.app', 'Contents'), { recursive: true });
        await hook(context(dir));
        assert.equal(fs.existsSync(path.join(dir, 'Carnivore.app', 'Contents', '_CodeSignature')), false);
    }
    const whole = path.join(tmp, 'mac-universal');
    fs.mkdirSync(path.join(whole, 'Carnivore.app', 'Contents'), { recursive: true });
    await assert.rejects(hook(context(whole)), undefined, 'the merged app is still signed (an empty bundle makes that fail loudly)');
});

const fuses = require(path.join(macDir, 'scripts', 'electron-fuses-check.js'));
const expected = FUSES;

test('the fuse reader accepts a hardened universal and names each wrong fuse on each slice', () => {
    const ok = fuses.readSliceWires(universal(HARDENED_WIRE));
    assert.deepEqual(ok.map((s) => s.arch), ['arm64', 'x86_64']);
    assert.deepEqual(fuses.mismatches(ok, expected), []);
    const stock = fuses.mismatches(fuses.readSliceWires(universal(STOCK_WIRE)), expected);
    assert.ok(stock.some((l) => /arm64 slice: runAsNode is on, expected off/.test(l)), stock.join('\n'));
    assert.ok(stock.some((l) => /x86_64 slice: enableNodeCliInspectArguments is on, expected off/.test(l)));
    assert.ok(stock.some((l) => /enableEmbeddedAsarIntegrityValidation is off, expected on/.test(l)));
    const noWasm = fuses.mismatches(fuses.readSliceWires(universal([...HARDENED_WIRE.slice(0, 8), 0])), expected);
    assert.ok(noWasm.some((l) => /WasmTrapHandlers/.test(l)));
});

test('the fuse reader judges the SECOND slice, which getCurrentFuseWire never reads', () => {
    const second = fuses.mismatches(fuses.readSliceWires(universal(HARDENED_WIRE, [1, ...HARDENED_WIRE.slice(1)])), expected);
    assert.equal(second.length, 1, second.join('\n'));
    assert.match(second[0], /^x86_64 slice: runAsNode is on/);
});

test('the fuse reader refuses a thin binary, a missing slice, a missing or doubled sentinel and a wire it cannot read', () => {
    assert.throws(() => fuses.readSliceWires(sliceBytes(HARDENED_WIRE)), /not a universal/);
    assert.throws(() => fuses.readSliceWires(fatBinary([[ARM64, sliceBytes(HARDENED_WIRE)]])), /no x86_64 slice/);
    assert.throws(() => fuses.readSliceWires(fatBinary([[ARM64, sliceBytes(HARDENED_WIRE)], [X86_64, Buffer.alloc(200, 3)]])), /x86_64 slice has no fuse sentinel/);
    assert.throws(() => fuses.readSliceWires(fatBinary([[ARM64, sliceBytes(HARDENED_WIRE, 2)], [X86_64, sliceBytes(HARDENED_WIRE)]])), /more than one fuse sentinel/);
    assert.throws(() => fuses.readSliceWires(universal(HARDENED_WIRE.slice(0, 5))), /shorter than/);
    assert.deepEqual(fuses.readSliceWires(fatBinary([[ARM64, sliceBytes(HARDENED_WIRE)], [X86_64, sliceBytes(HARDENED_WIRE)]], true)).length, 2, 'the 64 bit fat header reads too');
});

test('the fuse table in package.json: absent, partial, unknown or weakened is refused', () => {
    const withFuses = (mutate) => { const p = JSON.parse(JSON.stringify(realPkg)); mutate(p.build); return p; };
    fuses.checkPackage(realPkg);
    assert.throws(() => fuses.checkPackage(withFuses((b) => { delete b.electronFuses; })), /no build.electronFuses/);
    assert.throws(() => fuses.checkPackage(withFuses((b) => { delete b.electronFuses.onlyLoadAppFromAsar; })), /onlyLoadAppFromAsar must be true or false/);
    assert.throws(() => fuses.checkPackage(withFuses((b) => { b.electronFuses.fancy = true; })), /"fancy"/);
    assert.throws(() => fuses.checkPackage(withFuses((b) => { b.electronFuses.runAsNode = true; })), /runAsNode is true, the hardened floor is false/);
    assert.throws(() => fuses.checkPackage(withFuses((b) => { b.electronFuses.enableEmbeddedAsarIntegrityValidation = false; })), /the hardened floor is true/);
});

const bin = path.join(tmp, 'bin');
fs.mkdirSync(bin);
fs.mkdirSync(path.join(tmp, 'Library', 'Keychains'), { recursive: true });
const npmLog = path.join(tmp, 'npm.log');
const okRegistry = registry(tmp, String(specOf(realPkg, 'electron')));
const stub = (name, body) => fs.writeFileSync(path.join(bin, name), `#!/bin/bash\n${body}\n`, { mode: 0o755 });
stub('aws', 'exit 1');
stub('security', 'exit 1');
stub('lipo', 'exit 1');
stub('npm', `if [ "$1" = view ]; then cat "${okRegistry}"; exit 0; fi
echo "npm $*" >> "${npmLog}"
out=dist; for a in "$@"; do case "$a" in -c.directories.output=*) out="\${a#*=}";; esac; done
if [ -n "$BUILT_BINARY" ]; then d="$out/mac-universal/Carnivore.app/Contents/Frameworks/Electron Framework.framework/Versions/A"; mkdir -p "$d"; cp "$BUILT_BINARY" "$d/Electron Framework"; fi`);
function release(env = {}, args = [], mutate = () => {}) {
    const m = mirror(repo, tmp, mutate);
    const out = path.join(tmp, `out-${path.basename(m.root)}`);
    fs.rmSync(npmLog, { force: true });
    const r = spawnSync('bash', [m.releaseSh, `-c.directories.output=${out}`, ...args], {
        encoding: 'utf8', env: { ...process.env, HOME: tmp, PATH: `${bin}:${process.env.PATH}`, ...env },
    });
    return { ...r, ran: fs.existsSync(npmLog), out };
}
function binaryFile(name, buf) {
    const file = path.join(tmp, name);
    fs.writeFileSync(file, buf);
    return file;
}
const goodBinary = binaryFile('good.bin', universal(HARDENED_WIRE));
const stockBinary = binaryFile('stock.bin', universal(STOCK_WIRE));
const secondBinary = binaryFile('second.bin', universal(HARDENED_WIRE, [1, ...HARDENED_WIRE.slice(1)]));

test('release-build: a build with hardened fuses on both slices passes the read', () => {
    const r = release({ BUILT_BINARY: goodBinary });
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stderr, /built binary fuses match package.json on arm64 and x86_64/);
    assert.equal(r.ran, true);
});

test('release-build: a built binary with stock fuses is refused after the build', () => {
    const r = release({ BUILT_BINARY: stockBinary });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /built Electron's fuses differ from package.json: arm64 slice: runAsNode is on/);
});

test('release-build: a binary whose SECOND slice is unflipped is refused', () => {
    const r = release({ BUILT_BINARY: secondBinary });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /x86_64 slice: runAsNode is on/);
});

test('release-build: a build that wrote no Electron Framework is refused', () => {
    const r = release({ BUILT_BINARY: '' });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /the build wrote no .*Electron Framework: cannot read its fuses/);
});

test('release-build: an argument that weakens a fuse is refused before any build, in every spelling', () => {
    for (const arg of ['-c.electronFuses.runAsNode=true', '--config.electronFuses.enableNodeCliInspectArguments=true', '-c.electron_fuses.runAsNode=true', '-c.electronFuses=x']) {
        const r = release({ BUILT_BINARY: goodBinary }, [arg]);
        assert.notEqual(r.status, 0, `${arg} must be refused`);
        assert.match(r.stderr, /refusing the build argument/);
        assert.equal(r.ran, false, `${arg}: the build must not run`);
    }
});

test('release-build: a package.json with the fuses weakened or absent is refused before any build', () => {
    for (const mutate of [(p) => { p.build.electronFuses.runAsNode = true; }, (p) => { delete p.build.electronFuses; }]) {
        const r = release({ BUILT_BINARY: goodBinary }, [], mutate);
        assert.notEqual(r.status, 0);
        assert.match(r.stderr, /electron-fuses-check: refusing the build/);
        assert.equal(r.ran, false);
    }
});

test('release-build: CARNIVORE_BUILD_PURPOSE=e2e-test is refused by name, the unhardened target is a separate script', () => {
    const r = release({ CARNIVORE_BUILD_PURPOSE: 'e2e-test', BUILT_BINARY: goodBinary });
    assert.notEqual(r.status, 0);
    assert.match(r.stderr, /e2e-test.*unhardened.*build-e2e-app\.sh/);
    assert.equal(r.ran, false);
    const e2e = fs.readFileSync(path.join(macDir, 'scripts', 'e2e', 'build-e2e-app.sh'), 'utf8');
    assert.match(e2e, /CarnivoreBuildPurpose=e2e-test/);
    assert.match(e2e, /-c\.electronFuses\.runAsNode=true/);
    assert.doesNotMatch(e2e, /release-build\.sh\s+"?\$/, 'the test target never goes through the release script');
    assert.deepEqual(realPkg.devDependencies['playwright-core'], '1.64.0', 'Playwright for _electron is an exact devDependency');
    assert.match(realPkg.scripts['package:e2e'], /build-e2e-app\.sh/);
    assert.doesNotMatch(JSON.stringify(realPkg.dependencies), /playwright/, 'and never a runtime dependency (it must not reach the asar)');
});

test('main.js takes the single-instance lock right after userData is relocated and before any module that starts a server', () => {
    const main = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
    const reloc = main.indexOf('relocateUserData(app)');
    const lock = main.indexOf('app.requestSingleInstanceLock()');
    const serverRequire = main.indexOf("require('./server-manager')");
    assert.ok(reloc > 0 && lock > reloc && serverRequire > lock, `order: relocate ${reloc}, lock ${lock}, server-manager ${serverRequire}`);
    assert.match(main, /if \(!hasSingleInstanceLock\) \{\s*app\.quit\(\)/, 'a second instance quits cleanly (exit 0, so KeepAlive SuccessfulExit=false never relaunches it)');
    assert.match(main, /app\.on\('second-instance'/);
});

test('second-instance.js: a second launch always means focus, and only a carnivore: argument or the exact --toggle is read from argv', () => {
    const { handleSecondInstance } = require(path.join(macDir, 'second-instance.js'));
    assert.deepEqual(handleSecondInstance(['/Applications/Carnivore.app/Contents/MacOS/Carnivore']), { focus: true, toggle: false, links: [] });
    for (const hostile of [undefined, null, 'x', {}, ['--inspect=0', '/etc/passwd', 'x'.repeat(100000)]]) {
        assert.deepEqual(handleSecondInstance(hostile), { focus: true, toggle: false, links: [] });
    }
    assert.deepEqual(handleSecondInstance(['x', '--inspect=0', 'carnivore://open?x=1']), { focus: true, toggle: false, links: ['carnivore://open?x=1'] });
});

test('fs-perms.js: a 0755 directory becomes 0700, a missing one is created 0700, a symlink and a file are left alone', () => {
    const { ensureDirMode, PRIVATE_DIR_MODE } = require(path.join(macDir, 'engine', 'fs-perms.js'));
    assert.equal(PRIVATE_DIR_MODE, 0o700);
    const logs = [];
    const log = (m) => logs.push(m);
    const mode = (p) => fs.lstatSync(p).mode & 0o777;
    const open = path.join(tmp, 'perm-open');
    fs.mkdirSync(open, { mode: 0o755 });
    fs.chmodSync(open, 0o755);
    assert.equal(mode(open), 0o755, 'population check: the fixture starts at 0755');
    assert.equal(ensureDirMode(open, 0o700, { log }), 'changed');
    assert.equal(mode(open), 0o700);
    assert.equal(ensureDirMode(open, 0o700, { log }), 'unchanged');
    const fresh = path.join(tmp, 'perm-new', 'server');
    assert.equal(ensureDirMode(fresh, 0o700, { log }), 'created');
    assert.equal(mode(fresh), 0o700);
    const target = path.join(tmp, 'perm-target');
    fs.mkdirSync(target, { mode: 0o755 });
    fs.chmodSync(target, 0o755);
    const link = path.join(tmp, 'perm-link');
    fs.symlinkSync(target, link);
    assert.equal(ensureDirMode(link, 0o700, { log }), 'symlink');
    assert.equal(mode(target), 0o755, 'the link target is not touched');
    const file = path.join(tmp, 'perm-file');
    fs.writeFileSync(file, 'x', { mode: 0o644 });
    assert.equal(ensureDirMode(file, 0o700, { log }), 'not-a-directory');
    assert.equal(mode(file), 0o644);
    assert.equal(logs.length, 2, logs.join('\n'));
    const broken = { lstatSync: () => { const e = new Error('no'); e.code = 'EACCES'; throw e; } };
    assert.equal(ensureDirMode(open, 0o700, { fs: broken, log }), 'failed', 'a failure is returned, never thrown');
});

test('bootstrap.js makes <userData>/server private before the Python check, so a machine with no Python still gets it', () => {
    const src = fs.readFileSync(path.join(macDir, 'bootstrap.js'), 'utf8');
    const call = src.indexOf('ensureDirMode(serverDir');
    const python = src.indexOf('await findSuitablePython()');
    assert.ok(call > 0 && python > call, `order: ensureDirMode ${call}, python ${python}`);
    assert.match(src, /require\('\.\/engine\/fs-perms'\)/);
});

const GATE = /senderFrame\s*[!=]==\s*event\.sender\.mainFrame|senderAllowed\(|fromWindow\(/;
function ungatedIpc(src, label) {
    const starts = [...src.matchAll(/ipcMain\.(?:handle|on|once)\(\s*[^,]+,\s*/g)];
    const found = [];
    starts.forEach((m, i) => {
        const end = Math.min(m.index + m[0].length + 500, i + 1 < starts.length ? starts[i + 1].index : Infinity);
        const body = src.slice(m.index + m[0].length, end);
        if (GATE.test(body)) return;
        const named = /^\s*([A-Za-z_$][\w$]*)/.exec(body);
        const def = named && new RegExp(`(?:function\\s+${named[1]}\\b|(?:const|let)\\s+${named[1]}\\s*=)([\\s\\S]{0,700})`).exec(src);
        if (!(def && GATE.test(def[1]))) found.push(`${label}: ${m[0].slice(0, 70).replace(/\s+/g, ' ')}`);
    });
    return { sites: starts.length, found };
}
test('every shell IPC receiver refuses a sub-frame: every ipcMain registration under macOS/ is gated', () => {
    let sites = 0;
    const missing = [];
    for (const file of shellSources()) {
        const src = fs.readFileSync(file, 'utf8');
        const r = ungatedIpc(src, path.relative(macDir, file));
        sites += r.sites;
        missing.push(...r.found);
    }
    assert.ok(sites >= 13, `population check: expected at least 13 ipcMain registrations, found ${sites}`);
    assert.deepEqual(missing, [], `ipcMain registrations with no senderFrame/senderAllowed/fromWindow gate:\n${missing.join('\n')}`);
});
test('the IPC gate scan goes red on a fixture: a new handler that skips the gate, and an empty scan', () => {
    const bad = "deps.ipcMain.handle('carnivore:new', async (event, id) => { return run(id); });\nipcMain.on('carnivore:x', unguarded);\nfunction unguarded(event) { return 1; }";
    assert.equal(ungatedIpc(bad, 'fixture').found.length, 2);
    assert.equal(ungatedIpc("ipcMain.on('x', onX);\nfunction onX(event) { if (event.senderFrame !== event.sender.mainFrame) return; }", 'f').found.length, 0);
    assert.equal(ungatedIpc('no registrations here', 'f').sites, 0);
});

test('senderAllowed answers only the window\'s own loopback origin; the app window loads loopback whenever the bind covers it', () => {
    const { senderAllowed } = require(path.join(macDir, 'desktop-settings.js'));
    const { resolveAppWindowUrl, resolvePublishedUrl } = require(path.join(macDir, 'published-url.js'));
    const frame = (url) => { const f = { url }; return { senderFrame: f, sender: { mainFrame: f } }; };
    const deps = (origin) => ({ appWindow: { origin: () => origin, ownsSender: () => true } });
    assert.equal(senderAllowed(frame('http://127.0.0.1:8000/'), deps('http://127.0.0.1:8000')), true);
    assert.equal(senderAllowed(frame('http://10.0.1.5:8000/'), deps('http://10.0.1.5:8000')), false, 'a LAN origin gets no bridge answers even when it is the window\'s own');
    assert.equal(senderAllowed(frame('http://127.0.0.1:8000/'), deps('http://10.0.1.5:8000')), false);
    const lan = { port: 8000, configuredHost: '0.0.0.0', measuredHost: '0.0.0.0', lanIp: '10.0.1.5' };
    assert.equal(resolvePublishedUrl(lan), 'http://10.0.1.5:8000', 'the browser address is still the LAN one');
    assert.equal(resolveAppWindowUrl(lan), 'http://127.0.0.1:8000');
    assert.equal(resolveAppWindowUrl({ ...lan, measuredHost: null }), 'http://127.0.0.1:8000');
    assert.equal(resolveAppWindowUrl({ ...lan, measuredHost: '127.0.0.1' }), 'http://127.0.0.1:8000');
    assert.equal(resolveAppWindowUrl({ ...lan, configuredHost: '10.0.1.5', measuredHost: '10.0.1.5' }), 'http://10.0.1.5:8000', 'bound to one LAN address: no loopback to use');
    assert.equal(resolveAppWindowUrl({ ...lan, port: null }), null);
});

await Promise.all(pending);
if (failures > 0) {
    console.log(`\n${failures} failed`);
    process.exit(1);
}
console.log('\nall passed');
