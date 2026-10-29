import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client');
const JS = fs.readFileSync(path.join(ROOT, 'js', 'ambient-ticker.js'), 'utf8');

function make() {
    const attrs = {}; const props = {};
    return { nodeType: 1, isConnected: true, attrs, covered: false, matches() { return this.covered; },
        setAttribute: (n, v) => { attrs[n] = v; }, hasAttribute: (n) => n in attrs,
        style: { setProperty: (n, v) => { props[n] = v; }, removeProperty: (n) => { delete props[n]; } },
        get step() { return props['--amb-step']; } };
}

function boot({ calm = false, hidden = false, still = false, reduced = false, off = new Set() } = {}) {
    const listeners = {}; const rootAttrs = {}; const state = { reduced, off, timers: new Map(), nextId: 1, mo: null, mq: null };
    if (calm) rootAttrs['data-calm'] = 'blur';
    if (still) rootAttrs['data-oc-still'] = '';
    const root = { getAttribute: (n) => (n in rootAttrs ? rootAttrs[n] : null), hasAttribute: (n) => n in rootAttrs };
    const document = { documentElement: root, hidden,
        addEventListener: (n, f) => { (listeners[n] = listeners[n] || []).push(f); } };
    const ctx = {
        document,
        window: { Motion: { reduced: () => state.reduced, typeOff: (id) => state.off.has(id) } },
        matchMedia: () => (state.mq = { addEventListener: (n, f) => { state.mqf = f; } }),
        MutationObserver: function (cb) {
            if (!state.mo) { state.mo = cb; this.observe = () => {}; return; }
            const o = state.cover = { cb, live: false };
            this.observe = () => { o.live = true; }; this.disconnect = () => { o.live = false; };
        },
        setInterval: (f, ms) => { const id = state.nextId++; state.timers.set(id, { f, ms }); return id; },
        clearInterval: (id) => { state.timers.delete(id); },
    };
    ctx.window.document = document;
    vm.runInNewContext(JS, ctx);
    const fire = (n, e) => (listeners[n] || []).slice().forEach((f) => f(e));
    const tick = () => state.timers.forEach((t) => t.f());
    return {
        state, fire, tick, rootAttrs, document,
        join: (el, type = 'dialog-glow') => fire('animationstart', { animationName: 'amb-join-' + type, target: el }),
        change: () => state.mo(),
        timers: () => state.timers.size,
    };
}

test('one 250 ms timer while a wearer is visible, however many wearers join', () => {
    const t = boot(); const a = make(); const b = make();
    t.join(a); t.join(b, 'avatar-spiral');
    assert.equal(t.timers(), 1);
    assert.equal([...t.state.timers.values()][0].ms, 250);
    assert.equal(a.attrs['data-amb'], '');
});

test('the step advances by one per tick on every wearer', () => {
    const t = boot(); const a = make(); const b = make();
    t.join(a); t.join(b, 'avatar-spiral');
    assert.equal(a.step, '0');
    t.tick(); assert.equal(a.step, '1'); assert.equal(b.step, '1');
    t.tick(); t.tick(); assert.equal(a.step, '3'); assert.equal(b.step, '3');
});

test('an unrelated animation never joins', () => {
    const t = boot(); t.fire('animationstart', { animationName: 'status-led-breathe', target: make() });
    assert.equal(t.timers(), 0);
});

test('zero timers when no wearer is connected, and the timer stops on the first tick after the last one goes', () => {
    const t = boot(); assert.equal(t.timers(), 0);
    const a = make(); t.join(a); assert.equal(t.timers(), 1);
    a.isConnected = false; t.tick();
    assert.equal(t.timers(), 0);
});

for (const [name, set, clear] of [
    ['calm', (t) => { t.rootAttrs['data-calm'] = 'blur'; }, (t) => { delete t.rootAttrs['data-calm']; }],
    ['data-oc-still', (t) => { t.rootAttrs['data-oc-still'] = ''; }, (t) => { delete t.rootAttrs['data-oc-still']; }],
    ['document.hidden', (t) => { t.document.hidden = true; }, (t) => { t.document.hidden = false; }],
]) {
    test(`${name} stops the timer, holds the step, and clearing it re-arms`, () => {
        const t = boot(); const a = make(); t.join(a); t.tick(); t.tick();
        set(t); t.change();
        assert.equal(t.timers(), 0);
        assert.equal(a.step, '2');
        clear(t); t.change();
        assert.equal(t.timers(), 1);
        t.tick(); assert.equal(a.step, '3');
    });
}

test('already calm at join time: no timer', () => {
    const t = boot({ calm: true }); t.join(make());
    assert.equal(t.timers(), 0);
});

test('carnivore:calm and visibilitychange re-evaluate in the same turn', () => {
    const t = boot(); const a = make(); t.join(a);
    t.rootAttrs['data-calm'] = 'blur'; t.fire('carnivore:calm', { detail: { calm: true } });
    assert.equal(t.timers(), 0);
    delete t.rootAttrs['data-calm']; t.document.hidden = true; t.fire('visibilitychange');
    assert.equal(t.timers(), 0);
    t.document.hidden = false; t.fire('visibilitychange');
    assert.equal(t.timers(), 1);
});

test('OS reduce motion (and the animations setting) removes the step: the still look; clearing re-arms', () => {
    const t = boot(); const a = make(); t.join(a); t.tick();
    t.state.reduced = true; t.state.mqf();
    assert.equal(t.timers(), 0);
    assert.equal(a.step, undefined);
    t.state.reduced = false; t.change();
    assert.equal(t.timers(), 1);
    assert.equal(a.step, '1');
});

test('a switched-off type stops only its own wearer, and the timer stays for the others', () => {
    const t = boot(); const ring = make(); const spiral = make();
    t.join(ring, 'dialog-glow'); t.join(spiral, 'avatar-spiral'); t.tick();
    t.state.off.add('dialog-glow'); t.change();
    assert.equal(ring.step, undefined);
    assert.equal(t.timers(), 1);
    t.tick(); assert.equal(spiral.step, '2'); assert.equal(ring.step, undefined);
    t.state.off.add('avatar-spiral'); t.change();
    assert.equal(t.timers(), 0);
    t.state.off.clear(); t.change();
    assert.equal(t.timers(), 1);
    assert.equal(ring.step, '2');
});

test('a wearer the pauser marked off-screen holds its step and, alone, leaves no timer; showing it again re-arms', () => {
    const t = boot(); const a = make(); t.join(a); t.tick();
    a.attrs['data-anim-offscreen'] = ''; t.fire('carnivore:amb-visibility');
    assert.equal(t.timers(), 0);
    assert.equal(a.step, '1');
    delete a.attrs['data-anim-offscreen']; t.fire('carnivore:amb-visibility');
    assert.equal(t.timers(), 1);
});

test('a wearer under a visibility cover holds and leaves no timer; lifting the cover (watched by a class observer only while covered) re-arms', () => {
    const t = boot(); const a = make(); t.join(a); t.tick();
    assert.equal(t.state.cover, undefined);
    a.covered = true; t.tick();
    assert.equal(t.timers(), 0);
    assert.equal(a.step, '1');
    assert.equal(t.state.cover.live, true);
    a.covered = false; t.state.cover.cb();
    assert.equal(t.timers(), 1);
    assert.equal(t.state.cover.live, false);
});

test('every cover in the ticker is also in animation-pause.css', () => {
    const css = fs.readFileSync(path.join(ROOT, 'css', 'animation-pause.css'), 'utf8');
    const covers = JS.match(/var COVERS = ([\s\S]*?);\n/)[1].replace(/['+\n]/g, '').split(',').map((x) => x.trim().replace(/\s+/g, ' '));
    assert.ok(covers.length >= 7);
    for (const c of covers) assert.ok(css.includes(c), c);
});

test('every amb-join keyframe names an animation type that has a rule in animation-types.css', () => {
    const css = fs.readFileSync(path.join(ROOT, 'css', 'animation-pause.css'), 'utf8');
    const types = fs.readFileSync(path.join(ROOT, 'css', 'animation-types.css'), 'utf8');
    const ids = [...css.matchAll(/@keyframes amb-join-([\w-]+)/g)].map((m) => m[1]);
    assert.ok(ids.length >= 2);
    for (const id of ids) assert.ok(types.includes('data-anim-off~="' + id + '"'), id);
});

test('no Motion helper on the page: the ticker installs nothing', () => {
    const ctx = { document: { documentElement: {}, addEventListener() { throw new Error('should not listen'); } }, window: {} };
    vm.runInNewContext(JS, ctx);
});

test('the sources carry no infinite animation for the ring or the spiral', () => {
    const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');
    const ring = strip(fs.readFileSync(path.join(ROOT, 'css', 'popup-focus.css'), 'utf8'));
    const chip = strip(fs.readFileSync(path.join(ROOT, 'css', 'session-sidebar-account-chip.css'), 'utf8'));
    assert.doesNotMatch(ring, /popup-focus-turn\s+6s|@keyframes\s+popup-focus-turn/);
    assert.doesNotMatch(chip, /infinite|@keyframes\s+session-sidebar-spiral-turn/);
    assert.match(ring, /\.popup-focus-turn > \.pf-sheen::before \{[^}]*transform: rotate\(calc\(var\(--amb-step, 0\) \* 15deg\)\)/);
    assert.match(chip, /\.spiral-turn \{[^}]*transform: rotate\(calc\(var\(--amb-step, 0\) \* 15deg\)\)/);
});
