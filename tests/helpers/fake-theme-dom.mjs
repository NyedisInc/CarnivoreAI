
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { pathToFileURL, fileURLToPath } from 'node:url';
import { createFakeCtx } from './fake-canvas-2d.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.join(__dirname, '..', '..');

export const themesDir = path.join(repoRoot, 'client', 'css', 'themes');

// ---------------------------------------------------------------------
// ---------------------------------------------------------------------

export function installEnv(opts = {}) {
    const rafPending = new Map();
    let rafSeq = 0;
    const winListeners = [];
    const docListeners = [];
    const mqlListeners = [];
    const body = { children: [] };
    const attrs = { ...(opts.attrs || {}) };
    const observers = [];


    const doc = {
        hidden: !!opts.hidden,
        documentElement: { dataset: {}, getAttribute: (k) => (k in attrs ? attrs[k] : null) },
        body,
        createElement(tag) {
            const el = {
                tagName: String(tag).toUpperCase(),
                style: {},
                width: 0,
                height: 0,
                parentNode: null,
                _ctx: null,
                setAttribute(k, v) { this[k] = v; },
                getContext() {
                    if (opts.contextFails) return null;
                    if (!this._ctx) this._ctx = createFakeCtx(this);
                    return this._ctx;
                },
            };
            return el;
        },
        addEventListener(type, fn) { docListeners.push({ type, fn }); },
        removeEventListener(type, fn) {
            const i = docListeners.findIndex((l) => l.type === type && l.fn === fn);
            if (i >= 0) docListeners.splice(i, 1);
        },
    };
    body.appendChild = (el) => { el.parentNode = body; body.children.push(el); return el; };
    body.removeChild = (el) => {
        const i = body.children.indexOf(el);
        if (i >= 0) body.children.splice(i, 1);
        el.parentNode = null;
        return el;
    };

    const mql = {
        matches: !!opts.reducedMotion,
        addEventListener(type, fn) { mqlListeners.push({ type, fn }); },
        removeEventListener(type, fn) {
            const i = mqlListeners.findIndex((l) => l.type === type && l.fn === fn);
            if (i >= 0) mqlListeners.splice(i, 1);
        },
    };

    const win = {
        innerWidth: opts.width || 1440,
        innerHeight: 900,
        devicePixelRatio: 2,
        matchMedia: () => mql,
        addEventListener(type, fn) { winListeners.push({ type, fn }); },
        removeEventListener(type, fn) {
            const i = winListeners.findIndex((l) => l.type === type && l.fn === fn);
            if (i >= 0) winListeners.splice(i, 1);
        },
    };

    globalThis.MutationObserver = class {
        constructor(cb) { this.cb = cb; this.options = null; this.live = false; observers.push(this); }
        observe(_target, options) { this.options = options; this.live = true; }
        disconnect() { this.live = false; }
    };

    globalThis.window = win;
    globalThis.document = doc;
    globalThis.getComputedStyle = () => ({ getPropertyValue: () => '' });
    globalThis.requestAnimationFrame = (fn) => {
        rafSeq += 1;
        rafPending.set(rafSeq, fn);
        return rafSeq;
    };
    globalThis.cancelAnimationFrame = (id) => { rafPending.delete(id); };
    Object.defineProperty(globalThis, 'performance', {
        value: { now: () => Number.MAX_SAFE_INTEGER },
        configurable: true,
        writable: true,
    });

    return {
        observers,
        setAttr(k, v) { if (v === null) delete attrs[k]; else attrs[k] = v; },
        fire() { for (const o of observers) if (o.live) o.cb([]); },
        rafPending, winListeners, docListeners, mqlListeners, body, doc, win, mql,
        flush(now) {
            const due = [...rafPending.entries()];
            for (const [id, fn] of due) {
                rafPending.delete(id);
                fn(now);
            }
        },
        canvas() { return body.children[0]; },
    };
}


export const effectThemes = fs.readdirSync(themesDir)
    .filter((d) => fs.existsSync(path.join(themesDir, d, 'theme.json')))
    .filter((d) => {
        const m = JSON.parse(fs.readFileSync(path.join(themesDir, d, 'theme.json'), 'utf8'));
        return !!m.effects;
    })
    .sort();

const mirrorDir = fs.mkdtempSync(path.join(os.tmpdir(), 'theme-effects-test-'));
process.on('exit', () => {
    try { fs.rmSync(mirrorDir, { recursive: true, force: true }); } catch (_) {}
});

function mirror(relDir, name) {
    const src = fs.readFileSync(path.join(themesDir, relDir, name), 'utf8');
    const outDir = path.join(mirrorDir, relDir);
    fs.mkdirSync(outDir, { recursive: true });
    const out = path.join(outDir, name.replace(/\.js$/, '.mjs'));
    fs.writeFileSync(out, src.replace(
        '../_shared/effects-base.js',
        '../_shared/effects-base.mjs',
    ));
    return out;
}

mirror('_shared', 'effects-base.js');

export function loadEffect(themeId) {
    const file = mirror(themeId, 'effects.js');
    const url = pathToFileURL(file).href + '?v=' + Math.random();
    return import(url);
}



export function loadHarness() {
    return import(pathToFileURL(path.join(mirrorDir, '_shared', 'effects-base.mjs')).href);
}
