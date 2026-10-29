// What this file can and cannot cover:

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..');
const macDir = path.join(repoRoot, 'macOS');
const assetsDir = path.join(macDir, 'assets');
const mainJs = fs.readFileSync(path.join(macDir, 'main.js'), 'utf8');
const pkg = JSON.parse(fs.readFileSync(path.join(macDir, 'package.json'), 'utf8'));
const launcherJs = fs.readFileSync(path.join(macDir, 'terminal-launcher.js'), 'utf8');
const serverActionsJs = fs.readFileSync(path.join(macDir, 'tray-menu', 'actions', 'server.js'), 'utf8');
const icnsPath = path.join(assetsDir, 'icon.icns');

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

function parseIcns(buf) {
    assert.equal(buf.subarray(0, 4).toString('latin1'), 'icns', 'missing icns magic');
    const declaredLength = buf.readUInt32BE(4);
    const entries = [];
    let off = 8;
    while (off < declaredLength) {
        const type = buf.subarray(off, off + 4).toString('latin1');
        const length = buf.readUInt32BE(off + 4);
        assert.ok(length >= 8, `entry ${type} has an impossible length ${length}`);
        entries.push({ type, length, data: buf.subarray(off + 8, off + length) });
        off += length;
    }
    assert.equal(off, declaredLength, 'icns entry table does not land on the declared end');
    return { declaredLength, entries };
}

function pngSize(buf) {
    const sig = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
    if (buf.length < 24 || !buf.subarray(0, 8).equals(sig)) return null;
    return { width: buf.readUInt32BE(16), height: buf.readUInt32BE(20) };
}


test('packaged build does not declare LSUIElement, so the Dock tile is registered at launch', () => {
    const info = pkg.build && pkg.build.mac && pkg.build.mac.extendInfo;
    assert.ok(info, 'build.mac.extendInfo is missing');
    assert.equal(
        'LSUIElement' in info, false,
        'LSUIElement must be absent: Carnivore is a Dock-first app (R1-03)'
    );
});

test('main.js sets the regular activation policy at module scope and never hides the Dock', () => {
    assert.ok(
        /app\.setActivationPolicy\('regular'\)/.test(mainJs),
        'main.js must call app.setActivationPolicy(\'regular\'); the plist does not apply to `electron .`'
    );
    assert.ok(
        /process\.platform !== 'darwin'/.test(mainJs),
        'the activation call must be platform guarded'
    );
    assert.ok(
        /^useRegularActivation\(\);$/m.test(mainJs),
        'useRegularActivation() must be invoked at module scope, before app ready'
    );
    assert.ok(!/app\.dock\.hide\(/.test(mainJs), 'main.js must not hide the Dock tile');
});


test('every window fronts the app when it is shown', () => {
    assert.ok(
        /app\.on\('browser-window-created'/.test(mainJs),
        'activation must be wired once for all windows, not per call site'
    );
    assert.ok(
        /win\.on\('show'/.test(mainJs),
        'the handler must run on show, which is when the window becomes visible'
    );
    assert.ok(
        /app\.focus\(\{ steal: true \}\)/.test(mainJs),
        'a window opened from the menu bar icon or a banner is not fronted for you; app.focus({steal:true}) is required'
    );
});

test('every dialog fronts the app before it is displayed', () => {
    for (const name of ['showErrorBox', 'showMessageBox', 'showMessageBoxSync']) {
        assert.ok(
            mainJs.includes(`'${name}'`),
            `${name} must be wrapped so it cannot open behind another app`
        );
    }
    assert.ok(
        /installDialogActivation\(\);/.test(mainJs),
        'the dialog wrappers must actually be installed'
    );
});

test('Open Terminal Logs routes to the default terminal, not a hardcoded Terminal.app', () => {
    assert.ok(
        /terminalLauncher\.openServerLogInDefaultTerminal\(/.test(serverActionsJs),
        'Tail Server Log in Terminal must go through the .command launcher'
    );
    assert.ok(
        !/osascript[^\n]*Terminal/.test(mainJs + serverActionsJs),
        'main.js must not hardcode Terminal.app any more; that is the fallback\'s job'
    );
});

test('the Terminal.app fallback opens the script with open -b, which raises the window (P7)', () => {
    assert.ok(
        /execFile\(OPEN_BIN, \['-b', TERMINAL_BUNDLE_ID, scriptPath\]/.test(launcherJs),
        'the fallback must open the tail script in Terminal.app with open -b'
    );
    assert.ok(
        !/execFile\('osascript', \['-e'/.test(launcherJs),
        'no AppleScript may drive Terminal.app any more (the Apple Events keys are leaving)'
    );
});


test('build points at the icns', () => {
    assert.equal(pkg.build.mac.icon, 'assets/icon.icns');
    assert.ok(fs.existsSync(icnsPath), 'assets/icon.icns does not exist');
});

test('icns is a structurally valid multi-resolution icon', () => {
    const buf = fs.readFileSync(icnsPath);
    const { declaredLength, entries } = parseIcns(buf);
    assert.equal(declaredLength, buf.length, 'icns declared length does not match the file size');

    const types = entries.map((e) => e.type);
    for (const required of ['ic07', 'ic08', 'ic09', 'ic10', 'ic11', 'ic12', 'ic13', 'ic14']) {
        assert.ok(types.includes(required), `icns is missing the ${required} representation`);
    }

    const expected = {
        ic07: 128, ic08: 256, ic09: 512, ic10: 1024,
        ic11: 32, ic12: 64, ic13: 256, ic14: 512,
    };
    for (const e of entries) {
        const want = expected[e.type];
        if (!want) continue;
        const size = pngSize(e.data);
        assert.ok(size, `${e.type} is not a PNG`);
        assert.equal(size.width, want, `${e.type} should be ${want}px wide, got ${size.width}`);
        assert.equal(size.height, want, `${e.type} should be ${want}px tall, got ${size.height}`);
    }
});

test('committed icns is current - it regenerates byte-identically from the committed artwork', () => {
    if (process.platform !== 'darwin') skip('sips and iconutil are macOS only');
    for (const tool of ['sips', 'iconutil']) {
        if (spawnSync('/usr/bin/which', [tool]).status !== 0) skip(`${tool} not available`);
    }
    const gen = path.join(assetsDir, 'generate-app-icon.sh');
    assert.ok(fs.existsSync(gen), 'generate-app-icon.sh is missing');

    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'icns-currency-'));
    try {
        fs.copyFileSync(path.join(assetsDir, 'AppIcon-1024.png'), path.join(tmp, 'AppIcon-1024.png'));
        fs.copyFileSync(gen, path.join(tmp, 'generate-app-icon.sh'));
        execFileSync('/bin/bash', ['generate-app-icon.sh'], { cwd: tmp, stdio: 'ignore' });
        const rebuilt = fs.readFileSync(path.join(tmp, 'icon.icns'));
        const committed = fs.readFileSync(icnsPath);
        assert.ok(
            rebuilt.equals(committed),
            'assets/icon.icns is STALE - it does not match AppIcon-1024.png. Re-run assets/generate-app-icon.sh.'
        );
    } finally {
        fs.rmSync(tmp, { recursive: true, force: true });
    }
});

await runQueue();
console.log(`${passes} passed, ${failures} failed, ${skips} skipped`);
if (failures > 0) process.exit(1);
console.log('ALL PASS');
