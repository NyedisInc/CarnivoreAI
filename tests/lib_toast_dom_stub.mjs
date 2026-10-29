// ----------------------------------------------------------------------

import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import CATALOG from '../client/js/i18n/catalog.en.js';

const ROOT = path.resolve(path.dirname(url.fileURLToPath(import.meta.url)), '..');
const RENDER_BATCH_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/toast-render-batch.js'), 'utf8');
const VERSION_ARBITRATION_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/toast-version-arbitration.js'), 'utf8');
const SRC = fs.readFileSync(path.join(ROOT, 'client/js/toast.js'), 'utf8');
// issue #55 split ToastManager's class body across three files that each
// extend ToastManager.prototype (client/js/api-toasts.js's pattern for
const GROUPING_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/toast-grouping.js'), 'utf8');
const RENDER_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/toast-render.js'), 'utf8');
const LIFECYCLE_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/toast-lifecycle.js'), 'utf8');
const ROW_MENU_ICONS_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/session-row-menu-icons.js'), 'utf8');
const SUMMARY_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/session-status-summary.js'), 'utf8');
const GROUP_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/toast-session-group.js'), 'utf8');


export class El {
    constructor(tag) {
        this.tagName = String(tag).toUpperCase();
        this.parentNode = null;
        this.childNodes = [];
        this._attrs = new Map();
        this._text = '';
        this._listeners = new Map();
        this.dataset = new Proxy({}, {
            set: (t, k, v) => {
                t[k] = String(v);
                this._attrs.set(dashed(k), String(v));
                return true;
            },
            get: (t, k) => t[k],
        });
        this.style = { setProperty: (k, v) => { this._css = this._css || {}; this._css[k] = v; } };
        const self = this;
        this.classList = {
            add(...c) { c.forEach((x) => self._classes().add(x)); self._syncClass(); },
            remove(...c) { c.forEach((x) => self._classes().delete(x)); self._syncClass(); },
            contains(c) { return self._classes().has(c); },
        };
    }
    _classes() {
        if (!this.__cls) this.__cls = new Set(
            (this._attrs.get('class') || '').split(/\s+/).filter(Boolean));
        return this.__cls;
    }
    _syncClass() { this._attrs.set('class', [...this._classes()].join(' ')); }
    get className() { return this._attrs.get('class') || ''; }
    set className(v) { this.__cls = new Set(String(v).split(/\s+/).filter(Boolean)); this._syncClass(); }
    setAttribute(n, v) { this._attrs.set(n, String(v)); }
    getAttribute(n) { const v = this._attrs.get(n); return v === undefined ? null : v; }
    set type(v) { this.setAttribute('type', v); }
    get type() { return this.getAttribute('type') || ''; }

    get textContent() {
        if (this.childNodes.length === 0) return this._text;
        return this.childNodes.map((c) => c.textContent).join('');
    }
    set textContent(v) { this.childNodes.forEach((c) => { c.parentNode = null; }); this.childNodes = []; this._text = String(v); }

    appendChild(n) {
        if (n.parentNode) n.parentNode.removeChild(n);
        n.parentNode = this; this._text = ''; this.childNodes.push(n); return n;
    }
    insertBefore(n, ref) {
        if (!ref) return this.appendChild(n);
        if (n.parentNode) n.parentNode.removeChild(n);
        const i = this.childNodes.indexOf(ref);
        n.parentNode = this; this._text = '';
        this.childNodes.splice(i === -1 ? this.childNodes.length : i, 0, n);
        return n;
    }
    removeChild(n) {
        const i = this.childNodes.indexOf(n);
        if (i !== -1) this.childNodes.splice(i, 1);
        n.parentNode = null; return n;
    }
    remove() { if (this.parentNode) this.parentNode.removeChild(this); }
    get firstChild() { return this.childNodes[0] || null; }
    get nextSibling() {
        if (!this.parentNode) return null;
        const s = this.parentNode.childNodes;
        return s[s.indexOf(this) + 1] || null;
    }
    _all(out) { for (const c of this.childNodes) { out.push(c); c._all(out); } return out; }
    _matches(sel) {
        const not = /:not\(\.([A-Za-z0-9_-]+)\)$/.exec(sel);
        if (not) {
            if (this._classes().has(not[1])) return false;
            sel = sel.slice(0, not.index);
        }
        const m = /^\.([A-Za-z0-9_-]+)(?:\[([a-z-]+)="((?:[^"\\]|\\.)*)"\])?$/.exec(sel);
        if (!m) throw new Error(`stub selector unsupported: ${sel}`);
        if (!this._classes().has(m[1])) return false;
        if (!m[2]) return true;
        return this.getAttribute(m[2]) === m[3].replace(/\\(.)/g, '$1');
    }
    querySelectorAll(sel) { return this._all([]).filter((e) => e._matches(sel)); }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
    addEventListener(t, fn) {
        if (!this._listeners.has(t)) this._listeners.set(t, []);
        this._listeners.get(t).push(fn);
    }
    click() { for (const fn of this._listeners.get('click') || []) fn({}); }
    fire(type, evt = {}) {
        evt.preventDefault = () => { evt.defaultPrevented = true; };
        for (const fn of this._listeners.get(type) || []) fn(evt);
        return evt;
    }
}

function dashed(k) { return 'data-' + String(k).replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()); }

export function makeEnv(narrow = false) {
    const container = new El('div');
    container.setAttribute('id', 'toast-container');
    const mql = { matches: !!narrow, _h: [], addEventListener(t, fn) { if (t === 'change') this._h.push(fn); } };
    const acked = [];
    const document = {
        createElement: (t) => new El(t),
        getElementById: (id) => (id === 'toast-container' ? container : null),
    };
    const window = {
        document,
        matchMedia: () => mql,
        API: { ackToast: (id) => { acked.push(id); return Promise.resolve(); } },
        requestAnimationFrame: (fn) => { fn(); return 1; },
        CloudeI18n: { t: (key, params = {}) => String(CATALOG[key] ?? key).replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? '')) },
    };
    window.window = window;
    const sandbox = {
        window, document, console,
        requestAnimationFrame: window.requestAnimationFrame,
        setTimeout, clearTimeout, Promise, CSS: undefined,
        WebSocket: { OPEN: 1 },
        TextEncoder,
    };
    vm.createContext(sandbox);
    vm.runInContext(SUMMARY_SRC, sandbox, { filename: 'session-status-summary.js' });
    vm.runInContext(GROUP_SRC, sandbox, { filename: 'toast-session-group.js' });
    vm.runInContext(RENDER_BATCH_SRC, sandbox, { filename: 'toast-render-batch.js' });
    vm.runInContext(VERSION_ARBITRATION_SRC, sandbox, { filename: 'toast-version-arbitration.js' });
    vm.runInContext(SRC, sandbox, { filename: 'toast.js' });
    vm.runInContext(GROUPING_SRC, sandbox, { filename: 'toast-grouping.js' });
    vm.runInContext(RENDER_SRC, sandbox, { filename: 'toast-render.js' });
    vm.runInContext(LIFECYCLE_SRC, sandbox, { filename: 'toast-lifecycle.js' });
    vm.runInContext(ROW_MENU_ICONS_SRC, sandbox, { filename: 'session-row-menu-icons.js' });
    if (!sandbox.ToastSessionGroup) {
        throw new Error(
            'toast-session-group.js did not export itself into the sandbox, so '
            + 'the manager would silently fall back to per-kind coalescing and '
            + 'every one-card-per-session assertion would measure nothing');
    }
    return { sandbox, container, mql, acked, mgr: window.ToastManager };
}

let seq = 0;
export function toast(kind, title, body = null, session = 's1', sessionName = null, color = '#ff8800') {
    seq += 1;
    return {
        id: `t${seq}`, session_id: session, session_name: sessionName, kind, title, body,
        color, acknowledged: false,
    };
}

export function cards(container) {
    return container.childNodes.filter((e) => e._classes().has('toast'));
}
export function overflow(container) {
    return container.childNodes.find((e) => e._classes().has('toast-overflow')) || null;
}


export function dismissAllRow(container) {
    return container.childNodes.find((e) => e._classes().has('toast-dismiss-all')) || null;
}

export function settle() {
    return new Promise((resolve) => setTimeout(resolve, 300));
}

const TERM_SRC = fs.readFileSync(path.join(ROOT, 'client/js/terminal.js'), 'utf8');
// The boot line is one call into client/js/terminal-client-factory.js
// now, and the register() that hands it the class is the first of the
// two lines, so it is what a loader cuts at to get the class alone.
// The boot below that line does more than construct: it refuses by
// name when the client factory did not load. A loader that wants the
// class alone has to cut above the whole boot, so terminal.js carries
// this marker line and says in place that it does not move.
const TERM_SINGLETON = '// THE CLASS ENDS ABOVE.';

export function loadTerminalClass(sandbox) {
    const cut = TERM_SRC.indexOf(TERM_SINGLETON);
    if (cut === -1) {
        throw new Error(
            'terminal.js no longer ends with its singleton line, so this '
            + 'loader is slicing something it does not understand - refusing '
            + 'to guess');
    }
    vm.runInContext(
        TERM_SRC.slice(0, cut) + '\nwindow.__TerminalClass = Terminal;',
        sandbox, { filename: 'terminal.js' });
    return sandbox.window.__TerminalClass;
}

export function fakeTerminal(Klass, sessionId) {
    const P = Klass.prototype;
    const self = {
        _wiring: {}, _m: P._m,
        _currentSession: sessionId ? { id: sessionId } : null,
        sent: [],
        ws: { readyState: 1, send: (b) => { self.sent.push(b); } },
    };
    for (const name of ['_unwrapSession', '_sessionId', '_noteUserInputToSession',
        '_sendUserBytes', 'sendKeyToTerminal', 'insertText', '_writeSynthetic']) {
        if (typeof P[name] !== 'function') {
            throw new Error(`terminal.js has no ${name}() any more`);
        }
        self[name] = P[name];
    }
    self.term = { paste: (d) => {
        if (self._sendUserBytes(new TextEncoder().encode(d))) self._noteUserInputToSession(d);
    } };
    return self;
}
