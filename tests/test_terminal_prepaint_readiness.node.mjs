import assert from 'node:assert/strict';
import test from 'node:test';
import vm from 'node:vm';
import fs from 'node:fs';

function harness() {
    const counts = { settle: 0, layout: 0, fonts: 0, fits: 0 };
    const box = { x: 0, y: 0, width: 800, height: 600 };
    const style = { visibility: 'visible', display: 'block', font: '14px mono', padding: '0px', borderWidth: '0px' };
    const container = { isConnected: true, clientWidth: 800, clientHeight: 600, getBoundingClientRect: () => box };
    const document = { visibilityState: 'visible', fonts: { status: 'loaded', ready: Promise.resolve() }, getElementById: () => container };
    let verdict = { fitted: true, reason: 'ok' }, frames = 2, navigation = 1;
    const window = {
        document, devicePixelRatio: 2, getComputedStyle: () => style,
        NavigationGeneration: { current: () => navigation },
        TerminalMetrics: {
            guardedFit: () => { counts.fits++; return verdict; },
            waitForFonts: async () => { counts.fonts++; return true; },
        },
        TerminalLayoutWait: {
            settleFrames: async () => { counts.settle++; return frames; },
            waitForLayout: async () => { counts.layout++; return { sized: true, timedOut: false }; },
        },
    };
    const context = vm.createContext({ window, setTimeout, console: { log() {}, warn() {} }, atob });
    for (const file of ['terminal-readiness.js', 'terminal-scrollback-paint.js']) {
        vm.runInContext(fs.readFileSync(new URL('../client/js/' + file, import.meta.url), 'utf8'), context);
    }
    const controller = {
        _connGen: 1, _navToken: 1, _sessionId: () => 'session-a',
        term: { options: { fontFamily: 'monospace', fontSize: 14 }, cols: 80, rows: 24, write() {} },
    };
    return { window, controller, container, counts, box, style, document,
        verdict: value => { verdict = value; }, frames: value => { frames = value; },
        navigate: () => { navigation++; },
        paint: () => window.TerminalScrollbackPaint.paint(controller, btoa('hello'), 'rejoin'),
        wait: () => window.TerminalReadiness.waitForContainer(container, controller),
    };
}

test('verified prepaint skips the duplicate font/frame wait exactly once and still measures for connect', async () => {
    const h = harness();
    assert.equal(await h.paint(), 'painted');
    assert.equal(h.counts.settle, 1);
    const result = await h.wait();
    assert.equal(result.sized, true);
    assert.equal(h.counts.layout, 0);
    assert.equal(h.counts.fonts, 0);
    assert.equal((await h.window.TerminalReadiness.measure(h.controller)).reason, 'ok');
    assert.equal(h.counts.fits, 2, 'prepaint fit never replaces the connect measurement');
    await h.wait();
    assert.equal(h.counts.layout, 1, 'a consumed checkpoint cannot be reused');
});

for (const [label, change] of [
    ['resize', h => { h.box.width++; }],
    ['font options', h => { h.controller.term.options.fontSize++; }],
    ['computed font', h => { h.style.font = '15px other'; }],
    ['fonts loading', h => { h.document.fonts.status = 'loading'; }],
    ['font load completed since prepaint', h => { h.document.fonts.ready = Promise.resolve(); }],
    ['DPR', h => { h.window.devicePixelRatio = 1; }],
    ['hidden tab', h => { h.document.visibilityState = 'hidden'; }],
    ['hidden container', h => { h.style.visibility = 'hidden'; }],
    ['detached container', h => { h.container.isConnected = false; }],
    ['zero box', h => { h.box.width = 0; }],
    ['grid', h => { h.controller.term.cols++; }],
    ['connection generation', h => { h.controller._connGen++; }],
    ['session', h => { h.controller._sessionId = () => 'session-b'; }],
    ['navigation generation', h => h.navigate()],
    ['terminal replacement', h => { h.controller.term = { ...h.controller.term }; }],
]) {
    test(label + ' invalidates the checkpoint and retains normal waits', async () => {
        const h = harness(); await h.paint(); change(h); await h.wait();
        assert.equal(h.counts.layout, 1); assert.equal(h.counts.fonts, 1);
    });
}

for (const reason of ['unvalidated', 'unguarded', 'xterm-css-not-applied']) {
    test(reason + ' prepaint cannot establish a checkpoint', async () => {
        const h = harness(); h.verdict({ fitted: reason !== 'xterm-css-not-applied', reason });
        await h.paint(); await h.wait(); assert.equal(h.counts.layout, 1);
    });
}

test('timed out prepaint frames and cold entry keep the existing fallback', async () => {
    const h = harness(); h.frames(1); await h.paint(); await h.wait();
    assert.equal(h.counts.layout, 1);
    const cold = harness(); await cold.wait(); assert.equal(cold.counts.layout, 1);
});

test('a checkpoint cannot cross controllers or a new empty prepaint', async () => {
    const h = harness(); await h.paint();
    await h.window.TerminalReadiness.waitForContainer(h.container, { ...h.controller });
    assert.equal(h.counts.layout, 1);
    await h.window.TerminalScrollbackPaint.paint(h.controller, '', 'rejoin');
    await h.wait(); assert.equal(h.counts.layout, 2);
});
