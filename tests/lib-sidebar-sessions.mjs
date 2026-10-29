
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import { installCloudeWeb, unrefTimer } from './helpers/cloude-web-sandbox.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
export const ROOT = path.join(__dirname, '..');

const counts = { passes: 0, failures: 0 };

export function results() { return counts; }

export async function test(name, fn) {
    try {
        await fn();
        counts.passes++;
        console.log(`ok - ${name}`);
    } catch (err) {
        counts.failures++;
        console.error(`NOT OK - ${name}`);
        console.error(err && err.stack ? err.stack : err);
    }
}

export function repoFile(...parts) {
    return fs.readFileSync(path.join(ROOT, ...parts), 'utf8');
}

export class El {
    constructor(tag, doc) {
        this.tagName = String(tag).toUpperCase();
        this.ownerDocument = doc;
        this.parentNode = null;
        this.childNodes = [];
        this._attrs = new Map();
        this._listeners = new Map();
        this._box = { top: 0, height: 20 };
        this.innerHTML = '';
        this._text = '';
        this.style = {};
        const self = this;
        this.dataset = new Proxy({}, {
            get(_, key) {
                return self.getAttribute(`data-${dashed(String(key))}`) ?? undefined;
            },
            set(_, key, value) {
                self.setAttribute(`data-${dashed(String(key))}`, value);
                return true;
            },
        });
        this.classList = {
            add: (c) => self._classes().add(c) && self._writeClasses(),
            remove: (c) => { const s = self._classes(); s.delete(c); self._writeClasses(s); },
            contains: (c) => self._classes().has(c),
        };
    }

    _classes() { return new Set((this.getAttribute('class') || '').split(/\s+/).filter(Boolean)); }

    _writeClasses(set) {
        if (set) this.setAttribute('class', Array.from(set).join(' '));
        return true;
    }

    setAttribute(name, value) { this._attrs.set(name, String(value)); }
    getAttribute(name) { const v = this._attrs.get(name); return v === undefined ? null : v; }
    hasAttribute(name) { return this._attrs.has(name); }
    removeAttribute(name) { this._attrs.delete(name); }

    get id() { return this.getAttribute('id') || ''; }
    set id(v) { this.setAttribute('id', v); }

    get className() { return this.getAttribute('class') || ''; }
    set className(v) { this.setAttribute('class', v == null ? '' : String(v)); }

    get textContent() { return this._text; }

    set textContent(v) {
        this._text = v == null ? '' : String(v);
        this.innerHTML = this._text
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    appendChild(node) {
        if (node.parentNode) node.parentNode.removeChild(node);
        node.parentNode = this;
        this.childNodes.push(node);
        return node;
    }

    removeChild(node) {
        const i = this.childNodes.indexOf(node);
        if (i !== -1) this.childNodes.splice(i, 1);
        node.parentNode = null;
        return node;
    }

    insertAdjacentElement(where, node) {
        const parent = this.parentNode;
        if (!parent) throw new Error('insertAdjacentElement on a detached node');
        if (node.parentNode) node.parentNode.removeChild(node);
        const at = parent.childNodes.indexOf(this);
        if (where === 'afterend') parent.childNodes.splice(at + 1, 0, node);
        else if (where === 'beforebegin') parent.childNodes.splice(at, 0, node);
        else throw new Error(`insertAdjacentElement: unsupported position ${where}`);
        node.parentNode = parent;
        return node;
    }

    _walk(out) {
        for (const c of this.childNodes) { out.push(c); c._walk(out); }
        return out;
    }

    matches(sel) {
        return sel.split(',').map((s) => s.trim()).some((one) => {
            if (one.startsWith('.')) return this._classes().has(one.slice(1));
            if (one.startsWith('[')) {
                const body = one.slice(1, -1);
                const eq = body.indexOf('=');
                if (eq === -1) return this.hasAttribute(body);
                const n = body.slice(0, eq);
                const v = body.slice(eq + 1).replace(/^["']|["']$/g, '');
                return this.getAttribute(n) === v;
            }
            return this.tagName === one.toUpperCase();
        });
    }

    closest(sel) {
        for (let n = this; n && n.matches; n = n.parentNode) if (n.matches(sel)) return n;
        return null;
    }

    querySelectorAll(sel) { return this._walk([]).filter((e) => e.matches(sel)); }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
    contains(node) { for (let n = node; n; n = n.parentNode) if (n === this) return true; return false; }

    addEventListener(type, fn) {
        if (!this._listeners.has(type)) this._listeners.set(type, []);
        this._listeners.get(type).push(fn);
    }

    focus() { this.ownerDocument.activeElement = this; }

    select() { this.selectedAll = true; }

    getBoundingClientRect() {
        return { top: this._box.top, height: this._box.height, bottom: this._box.top + this._box.height };
    }

    dispatchEvent(type, extra = {}) {
        const event = Object.assign({
            type, target: this, defaultPrevented: false, _stopped: false,
            preventDefault() { this.defaultPrevented = true; },
            stopPropagation() { this._stopped = true; },
        }, extra);
        for (let n = this; n; n = n.parentNode) {
            for (const fn of (n._listeners.get(type) || []).slice()) fn(event);
            if (event._stopped) break;
        }
        return event;
    }
}

export class Doc extends El {
    constructor() {
        super('#document', null);
        this.ownerDocument = this;
        this.activeElement = null;
        this.body = this.createElement('body');
        this.appendChild(this.body);
    }

    createElement(tag) { return new El(tag, this); }

    getElementById(id) { return this._walk([]).find((e) => e.getAttribute('id') === id) || null; }
}

function dashed(key) {
    return key.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`);
}

export function plain(value) {
    return JSON.parse(JSON.stringify(value));
}

export function names(rows) {
    return plain(Array.from(rows).map((r) => r.name));
}

export function fakeStorage(seed = {}, throws = false) {
    const map = new Map(Object.entries(seed));
    return {
        map,
        getItem(k) { if (throws) throw new Error('denied'); return map.has(k) ? map.get(k) : null; },
        setItem(k, v) { if (throws) throw new Error('denied'); map.set(k, String(v)); },
        removeItem(k) { map.delete(k); },
    };
}

export const MOVED_TO_BUNDLE = new Set([
    'session-sidebar.js', 'session-sidebar-refresh.js', 'session-sidebar-paint.js',
    'session-sidebar-fetch.js', 'session-sidebar-asleep.js', 'session-sidebar-row-identity.js',
    'session-listing-state.js', 'session-sidebar-store-keys.js', 'session-sidebar-store.js',
    'session-sidebar-store-rebind.js', 'session-sidebar-arrangement.js', 'session-sidebar-sync.js',
    'session-sidebar-group-store.js', 'session-sidebar-group-membership.js',
    'session-sidebar-group-order.js', 'session-sidebar-search.js', 'session-sidebar-groups-search.js',
    'session-sidebar-kind-groups.js', 'session-sidebar-pin.js', 'session-sidebar-resize.js',
    'session-sidebar-density.js', 'session-sidebar-bar.js', 'session-sidebar-footer.js',
    'session-sidebar-row-signature.js',
]);

export function loadModules(names, opts = {}) {
    const document = opts.document || new Doc();
    const storage = opts.storage || fakeStorage();
    const context = {
        console: { log() {}, warn() {}, error() {} },
        document,
        localStorage: storage,
        Date,
        JSON,
        Math,
        Set,
        Map,
        Array,
        Object,
        String,
        Number,
        Boolean,
        Promise,
        setTimeout: unrefTimer(setTimeout),
        clearTimeout,
        setInterval: unrefTimer(setInterval),
        clearInterval,
    };
    context.window = context;
    vm.createContext(context);
    let bundle = false;
    for (const name of names) {
        if (MOVED_TO_BUNDLE.has(name)) { bundle = true; continue; }
        const src = fs.readFileSync(path.join(ROOT, 'client', 'js', name), 'utf8');
        vm.runInContext(src, context, { filename: name });
    }
    if (bundle) {
        context.document = new Proxy(document, {
            get: (t, k) => (k === 'body' ? undefined : Reflect.get(t, k)),
        });
        try {
            installCloudeWeb(context);
        } finally {
            context.document = document;
        }
    }
    return { window: context, document, storage };
}
