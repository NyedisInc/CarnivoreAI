import { strict as assert } from 'node:assert';
import test from 'node:test';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'client');
const JS = fs.readFileSync(path.join(ROOT, 'js', 'animation-calm.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'css', 'animation-calm.css'), 'utf8');

function el() {
    const attrs = {}; const writes = [];
    return { nodeType: 1, writes, attrs,
        getAttribute: (n) => (n in attrs ? attrs[n] : null),
        setAttribute: (n, v) => { attrs[n] = v; writes.push(['set', n, v]); },
        removeAttribute: (n) => { delete attrs[n]; writes.push(['remove', n]); } };
}
const anim = (target, iterations, pseudoElement = null) => ({ effect: { target, pseudoElement, getComputedTiming: () => ({ iterations }) } });

function boot({ calm = false, anims = [] } = {}) {
    const listeners = {}; const rootAttrs = calm ? { 'data-calm': 'blur' } : {};
    let animations = anims; let marked = [];
    const root = { getAttribute: (n) => (n in rootAttrs ? rootAttrs[n] : null) };
    const document = {
        documentElement: root,
        addEventListener: (n, f) => { (listeners[n] = listeners[n] || []).push(f); },
        removeEventListener: (n, f) => { listeners[n] = (listeners[n] || []).filter((x) => x !== f); },
        getAnimations: () => animations,
        querySelectorAll: () => ({ forEach: (cb) => marked.forEach(cb) }),
    };
    const ctx = { document, getComputedStyle: (e) => ({ animationIterationCount: e.iter || '1' }) };
    vm.runInNewContext(JS, ctx);
    const fire = (n, e) => (listeners[n] || []).slice().forEach((f) => f(e));
    return { fire, listeners, setAnims: (a) => { animations = a; }, setMarked: (m) => { marked = m; } };
}

test('entry marks infinite self/::before/::after with exactly those tokens and skips finite ones', () => {
    const t = boot(); const a = el(); const b = el(); const c = el(); const fin = el();
    t.setAnims([anim(a, Infinity), anim(a, Infinity, '::before'), anim(b, Infinity, '::after'), anim(c, Infinity, '::before'), anim(c, Infinity, '::after'), anim(fin, 3)]);
    t.fire('carnivore:calm', { detail: { calm: true, reasons: ['blur'] } });
    assert.equal(a.attrs['data-anim-calm'], 'self before');
    assert.equal(b.attrs['data-anim-calm'], 'after');
    assert.equal(c.attrs['data-anim-calm'], 'before after');
    assert.deepEqual(fin.writes, []);
});

test('already calm at load marks at once', () => {
    const a = el(); const t = boot({ calm: true, anims: [anim(a, Infinity)] });
    assert.equal(a.attrs['data-anim-calm'], 'self');
    assert.equal((t.listeners.animationstart || []).length, 1);
});

test('animationstart while calm marks infinite ones only, and stops listening on exit', () => {
    const t = boot(); t.fire('carnivore:calm', { detail: { calm: true } });
    const inf = Object.assign(el(), { iter: 'infinite' }); const fin = Object.assign(el(), { iter: '1' });
    t.fire('animationstart', { target: inf, pseudoElement: '::after' });
    t.fire('animationstart', { target: fin });
    assert.equal(inf.attrs['data-anim-calm'], 'after');
    assert.deepEqual(fin.writes, []);
    t.fire('carnivore:calm', { detail: { calm: false } });
    assert.equal((t.listeners.animationstart || []).length, 0);
});

test('a stale marker is removed on the next entry', () => {
    const t = boot(); const stale = el(); stale.attrs['data-anim-calm'] = 'self';
    t.setMarked([stale]); t.setAnims([]);
    t.fire('carnivore:calm', { detail: { calm: true } });
    assert.deepEqual(stale.writes, [['remove', 'data-anim-calm']]);
});

test('exit writes no attribute', () => {
    const t = boot(); const a = el(); t.setAnims([anim(a, Infinity)]);
    t.fire('carnivore:calm', { detail: { calm: true } });
    const before = a.writes.length;
    t.fire('carnivore:calm', { detail: { calm: false } });
    assert.equal(a.writes.length, before);
});

test('stylesheet: three pause rules, the reduce backstop, and no animation: none outside it', () => {
    const css = CSS.replace(/\/\*[\s\S]*?\*\//g, '');
    assert.match(css, /:root\[data-calm\] \[data-anim-calm~="self"\]\s*\{\s*animation-play-state: paused !important/);
    assert.match(css, /\[data-anim-calm~="before"\]::before\s*\{\s*animation-play-state: paused !important/);
    assert.match(css, /\[data-anim-calm~="after"\]::after\s*\{\s*animation-play-state: paused !important/);
    const m = css.match(/@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*?animation: none !important;[\s\S]*?\}\s*\}/);
    assert.ok(m, 'reduce backstop present');
    assert.equal(css.replace(m[0], '').includes('animation: none'), false);
    assert.match(css, /@layer legacy/);
});
