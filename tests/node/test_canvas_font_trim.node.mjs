import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import assert from 'node:assert/strict';

const ROOT = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const SRC = fs.readFileSync(path.join(ROOT, 'client', 'js', 'canvas-font-trim.js'), 'utf8');

function page(rejects) {
    class Ctx {}
    Object.defineProperty(Ctx.prototype, 'font', {
        configurable: true,
        get() { return this._f || '10px sans-serif'; },
        set(v) { if (rejects && /^\s/.test(v)) return; this._f = v.trim(); }
    });
    const g = { CanvasRenderingContext2D: Ctx, OffscreenCanvas: class { getContext() { return new Ctx(); } } };
    g.window = g;
    vm.runInNewContext(SRC, g);
    return { g, Ctx };
}

let bad = 0;
for (const [name, fn] of Object.entries({
    'installs and trims when the browser rejects a leading space'() {
        const { g, Ctx } = page(true);
        const c = new Ctx();
        c.font = ' 400 14px monospace';
        assert.equal(c.font, '400 14px monospace');
        assert.equal(g.CanvasFontTrim.install(g).length, 0); // idempotent
    },
    'does not install when the browser accepts a leading space'() {
        const { Ctx } = page(false);
        const c = new Ctx();
        c.font = ' 14px monospace';
        assert.equal(Object.getOwnPropertyDescriptor(Ctx.prototype, 'font').set.__fontTrim, undefined);
        assert.equal(c.font, '14px monospace');
    },
})) {
    try { fn(); console.log(`ok - ${name}`); } catch (e) { bad++; console.error(`NOT OK - ${name}\n${e.stack}`); }
}
if (bad) process.exit(1);
console.log('ALL PASS');
