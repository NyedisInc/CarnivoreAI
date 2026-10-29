
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.join(HERE, '..', 'client', 'js', 'terminal-layout-wait.js');

function load({ painting }) {
    const rafRequests = [];
    const sandbox = {
        setTimeout,
        clearTimeout,
        Date,
        console: { warn() {}, log() {} },
        requestAnimationFrame(cb) {
            rafRequests.push(cb);
            if (painting) setTimeout(() => cb(1), 0);
        }
    };
    sandbox.window = sandbox;
    sandbox.globalThis = sandbox;
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(SRC, 'utf8'), sandbox, { filename: SRC });
    return { api: sandbox.TerminalLayoutWait, rafRequests };
}

function el(w, h) {
    return { offsetWidth: w, offsetHeight: h };
}

let failures = 0;
async function check(name, fn) {
    try {
        await fn();
        console.log(`  ok  ${name}`);
    } catch (e) {
        failures++;
        console.log(`FAIL  ${name}\n      ${e && e.message}`);
    }
}

console.log('terminal-layout-wait');


await check('an UNPAINTED tab resolves instead of hanging forever', async () => {
    const { api, rafRequests } = load({ painting: false });
    const started = Date.now();
    const result = await Promise.race([
        api.waitForLayout(el(1741, 724), { frameTimeoutMs: 30 }),
        new Promise((_, rej) => setTimeout(() => rej(new Error('HUNG: never resolved')), 2000))
    ]);
    assert.equal(result.sized, true, 'the box was measurable');
    assert.equal(result.timedOut, true, 'must report that it gave up on paint');
    assert.equal(result.framesPainted, 0, 'no frame was painted');
    assert.equal(rafRequests.length, api.FRAME_COUNT, 'still requested its frames');
    assert.ok(Date.now() - started < 1500, 'bounded, not merely finite');
});

await check('an unpainted tab with a ZERO-SIZE container still resolves', async () => {
    const { api } = load({ painting: false });
    const result = await Promise.race([
        api.waitForLayout(el(0, 0), { sizeTimeoutMs: 60, frameTimeoutMs: 20 }),
        new Promise((_, rej) => setTimeout(() => rej(new Error('HUNG: never resolved')), 2000))
    ]);
    assert.equal(result.sized, false, 'never got a box, and says so');
    assert.equal(result.timedOut, true);
});

await check('a null container is not fatal', async () => {
    const { api } = load({ painting: false });
    const result = await api.waitForLayout(null, { sizeTimeoutMs: 40, frameTimeoutMs: 20 });
    assert.equal(result.sized, false);
    assert.equal(result.timedOut, true);
});

await check('a missing requestAnimationFrame is not fatal', async () => {
    const { api } = load({ painting: false });
    const result = await Promise.race([
        (async () => {
            const painted = await api.nextFrameOrTimeout(25);
            return painted;
        })(),
        new Promise((_, rej) => setTimeout(() => rej(new Error('HUNG')), 1500))
    ]);
    assert.equal(result, false, 'timer settles it');
});


await check('a PAINTED tab still waits for its frames (not short-circuited)', async () => {
    const { api, rafRequests } = load({ painting: true });
    const result = await api.waitForLayout(el(1741, 724), { frameTimeoutMs: 500 });
    assert.equal(result.sized, true);
    assert.equal(result.timedOut, false, 'a painted tab never reports a timeout');
    assert.equal(result.framesPainted, api.FRAME_COUNT, 'both frames were awaited');
    assert.equal(rafRequests.length, api.FRAME_COUNT);
});

await check('a painted tab waits out a container that gains its box late', async () => {
    const { api } = load({ painting: true });
    const box = el(0, 0);
    setTimeout(() => { box.offsetWidth = 800; box.offsetHeight = 400; }, 40);
    const result = await api.waitForLayout(box, { sizeTimeoutMs: 1000, frameTimeoutMs: 500 });
    assert.equal(result.sized, true, 'picked up the box once it appeared');
    assert.equal(result.timedOut, false);
});


await check('nextFrameOrTimeout reports which one won', async () => {
    const painted = load({ painting: true });
    assert.equal(await painted.api.nextFrameOrTimeout(500), true);
    const dark = load({ painting: false });
    assert.equal(await dark.api.nextFrameOrTimeout(25), false);
});

await check('nextFrameOrTimeout settles exactly once', async () => {
    const { api, rafRequests } = load({ painting: false });
    let settles = 0;
    const p = api.nextFrameOrTimeout(20).then(() => { settles++; });
    await p;
    rafRequests.forEach((cb) => cb(1));
    await new Promise((r) => setTimeout(r, 30));
    assert.equal(settles, 1, 'a late frame must not re-resolve');
});


await check('settleFrames resolves in an UNPAINTED tab', async () => {
    const { api } = load({ painting: false });
    const painted = await Promise.race([
        api.settleFrames(2, 25),
        new Promise((_, rej) => setTimeout(() => rej(new Error('HUNG: never resolved')), 1500))
    ]);
    assert.equal(painted, 0, 'no frame painted, and it says so');
});

await check('settleFrames still awaits real frames in a PAINTED tab', async () => {
    const { api, rafRequests } = load({ painting: true });
    const painted = await api.settleFrames(2, 500);
    assert.equal(painted, 2, 'both frames were genuinely awaited');
    assert.equal(rafRequests.length, 2);
});

await check('terminal.js has no bare rAF await left on the connect path', async () => {
    const src = fs.readFileSync(
        path.join(HERE, '..', 'client', 'js', 'terminal.js'), 'utf8');
    assert.equal(
        src.indexOf('new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))'),
        -1,
        'a bare double-rAF await is a permanent hang in an unpainted tab'
    );
    assert.equal(
        src.indexOf('await new Promise(requestAnimationFrame)'), -1,
        'a bare single-rAF await is the same defect'
    );
});

await check('hasBox refuses zero and missing elements', async () => {
    const { api } = load({ painting: true });
    assert.equal(api.hasBox(el(10, 10)), true);
    assert.equal(api.hasBox(el(0, 10)), false);
    assert.equal(api.hasBox(el(10, 0)), false);
    assert.equal(api.hasBox(null), false);
});

if (failures) {
    console.error(`\n${failures} assertion group(s) failed`);
    process.exit(1);
}
console.log('\nall ok');
