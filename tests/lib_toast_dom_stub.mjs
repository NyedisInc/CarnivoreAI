// ----------------------------------------------------------------------

import fs from 'node:fs';
import path from 'node:path';
import url from 'node:url';
import vm from 'node:vm';
import CATALOG from '../client/js/i18n/catalog.en.js';
import { installTrOnly } from './helpers/catalog-tr.mjs';

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
    path.join(ROOT, 'client/js/toast-view.js'), 'utf8');
const LIFECYCLE_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/toast-lifecycle.js'), 'utf8');
const ROW_MENU_ICONS_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/session-row-menu-icons.js'), 'utf8');
const SUMMARY_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/session-status-summary.js'), 'utf8');
const GROUP_SRC = fs.readFileSync(
    path.join(ROOT, 'client/js/toast-session-group.js'), 'utf8');


export class ViewEl {
    constructor(tag, { cls = [], attrs = {}, text = '', kids = [], on = {} } = {}) {
        this.tagName = String(tag).toUpperCase();
        this.parentNode = null;
        this.childNodes = kids;
        kids.forEach((k) => { k.parentNode = this; });
        this._cls = new Set(cls);
        this._attrs = new Map(Object.entries(tag === 'button' ? { type: 'button', ...attrs } : attrs).filter(([, v]) => v !== undefined && v !== null).map(([k, v]) => [k, String(v)]));
        this._text = text;
        this._on = on;
        const self = this;
        this.classList = { contains: (c) => self._cls.has(c) };
        this.dataset = new Proxy({}, {
            get: (_t, k) => self._attrs.get('data-' + String(k).replace(/[A-Z]/g, (ch) => '-' + ch.toLowerCase())),
        });
    }
    get className() { return [...this._cls].join(' '); }
    getAttribute(n) { const v = this._attrs.get(n); return v === undefined ? null : v; }
    get type() { return 'button'; }
    get textContent() { return this.childNodes.length ? this.childNodes.map((c) => c.textContent).join('') : this._text; }
    get firstChild() { return this.childNodes[0] || null; }
    get nextSibling() {
        if (!this.parentNode) return null;
        const s = this.parentNode.childNodes;
        return s[s.indexOf(this) + 1] || null;
    }
    _all(out) { for (const c of this.childNodes) { out.push(c); c._all(out); } return out; }
    querySelectorAll(sel) {
        const m = /^\.([A-Za-z0-9_-]+)$/.exec(sel);
        if (!m) throw new Error(`stub selector unsupported: ${sel}`);
        return this._all([]).filter((e) => e._cls.has(m[1]));
    }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
    fire(type, evt = {}) {
        evt.preventDefault = () => { evt.defaultPrevented = true; };
        let stopped = false;
        evt.stopPropagation = () => { stopped = true; };
        for (let n = this; n && !stopped; n = n.parentNode) {
            if (n._on[type]) n._on[type](evt);
        }
        return evt;
    }
    click() { return this.fire('click', {}); }
}

class ViewContainer {
    constructor(getManager) {
        this._getManager = getManager;
        this._cache = { view: null, nodes: [] };
        this.tagName = 'DIV';
    }
    getAttribute(n) { return n === 'id' ? 'toast-container' : null; }
    get childNodes() {
        const view = this._getManager()._view;
        if (this._cache.view !== view) this._cache = { view, nodes: projectView(this._getManager(), view) };
        return this._cache.nodes;
    }
    get firstChild() { return this.childNodes[0] || null; }
    querySelectorAll(sel) {
        const m = /^\.([A-Za-z0-9_-]+)$/.exec(sel);
        if (!m) throw new Error(`stub selector unsupported: ${sel}`);
        return this.childNodes.filter((e) => e._cls.has(m[1]));
    }
    querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}

function projectView(mgr, view) {
    const out = [];
    if (view.dismissAll) {
        const { total, blocking } = view.dismissAll;
        out.push(new ViewEl('button', {
            cls: ['toast-dismiss-all'],
            attrs: { 'data-total': total, 'data-blocking': blocking,
                'aria-label': tr(blocking ? 'toast.dismiss_all.label_blocking' : 'toast.dismiss_all.label', { total, blocking }) },
            text: tr('toast.dismiss_all.text', { total }), on: { click: () => mgr.dismissAll() },
        }));
    }
    if (view.waiting) {
        out.push(new ViewEl('div', { cls: ['toast-waiting'], attrs: { 'data-count': view.waiting, role: 'status' },
            text: `${view.waiting} sessions waiting` }));
    }
    for (const card of view.cards) out.push(projectCard(mgr, card));
    if (view.overflow) {
        const o = view.overflow;
        const text = o.expanded ? tr('toast.show_fewer')
            : tr('toast.overflow.more', { count: o.count }) + (o.worstCount !== null ? tr('toast.overflow.worst', { count: o.worstCount }) : '');
        out.push(new ViewEl('button', {
            cls: ['toast-overflow'],
            attrs: { 'data-hidden-count': o.expanded ? 0 : o.count, 'data-worst-severity': o.worst, 'data-severity': o.worst, 'aria-expanded': o.expanded },
            text, on: { click: () => mgr.toggleOverflow() },
        }));
    }
    return out;
}

function tr(key, params = {}) { return globalThis.__toastStubWindow.CloudeI18n.t(key, params); }

function projectCard(mgr, card) {
    const key = card.key;
    const kids = [];
    const title = [];
    if (card.sleepIcon !== null) title.push(new ViewEl('span', { cls: ['toast__title-icon'], text: card.sleepIcon }));
    title.push(new ViewEl('span', { cls: ['toast__title-text'], text: card.title || tr('toast.untitled') }));
    if (card.badgeCount > 1) {
        title.push(new ViewEl('span', { cls: ['toast__count'], attrs: { 'aria-label': tr('toast.count.label', { count: card.badgeCount }) },
            text: tr('toast.count.badge', { count: card.badgeCount }) }));
    }
    kids.push(new ViewEl('div', { cls: ['toast__title'], kids: title }));
    kids.push(new ViewEl(card.session.canNavigate ? 'button' : 'div', {
        cls: ['toast__session'], attrs: { 'data-unknown': card.session.unknown ? '1' : undefined },
        text: card.session.text, on: card.session.canNavigate ? { click: () => mgr.clickSession(key) } : {},
    }));
    if (card.body) kids.push(new ViewEl('div', { cls: ['toast__body'], text: card.body }));
    if (card.actionLabel) {
        kids.push(new ViewEl('button', { cls: ['toast__action'], text: card.actionLabel,
            on: { click: (e) => { e.stopPropagation(); mgr.runCardAction(key); } } }));
    }
    const dismissLabel = tr(card.count > 1 ? 'toast.dismiss.many' : 'toast.dismiss.one', { count: card.count });
    kids.push(new ViewEl('button', { cls: ['toast__dismiss'], attrs: { 'aria-label': dismissLabel, title: dismissLabel }, text: '\u00d7',
        on: { click: (e) => { e.stopPropagation(); mgr.dismissGroup(key); } } }));
    const open = () => { if (card.clickable) mgr.openGroup(key); };
    const node = new ViewEl('div', {
        cls: ['toast', ...(card.dismissing ? ['toast--dismissing'] : []), ...(card.clickable ? ['toast--clickable'] : [])],
        attrs: {
            'data-group-key': key, 'data-toast-id': card.id, 'data-kind': card.kind, 'data-severity': card.severity,
            'data-count': card.count, 'data-mode': card.mode, 'data-session-id': card.sessionId, role: card.role,
            'data-alert-severity': card.alertSeverity ?? undefined, 'data-themed': card.color ? '1' : undefined,
            'data-accent': card.color ?? undefined,
        },
        kids,
        on: {
            click: open,
            keydown: (e) => { if (card.clickable && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); open(); } },
            mousedown: (e) => { if (e.button === 1) e.preventDefault(); },
            auxclick: (e) => { if (e.button === 1) { e.preventDefault(); mgr.dismissGroup(key); } },
        },
    });
    node._css = card.color ? { '--toast-accent': card.color } : undefined;
    return node;
}

export function makeEnv(narrow = false) {
    let manager = null;
    const container = new ViewContainer(() => manager);
    const mql = { matches: !!narrow, _h: [], addEventListener(t, fn) { if (t === 'change') this._h.push(fn); } };
    const acked = [];
    const document = {
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
    globalThis.__toastStubWindow = window;
    const sandbox = {
        window, document, console, CloudeI18n: window.CloudeI18n,
        requestAnimationFrame: window.requestAnimationFrame,
        setTimeout, clearTimeout, Promise, CSS: undefined,
        WebSocket: { OPEN: 1 },
        TextEncoder,
    };
    vm.createContext(sandbox);
    installTrOnly(sandbox);
    vm.runInContext(SUMMARY_SRC, sandbox, { filename: 'session-status-summary.js' });
    vm.runInContext(GROUP_SRC, sandbox, { filename: 'toast-session-group.js' });
    vm.runInContext(RENDER_BATCH_SRC, sandbox, { filename: 'toast-render-batch.js' });
    vm.runInContext(VERSION_ARBITRATION_SRC, sandbox, { filename: 'toast-version-arbitration.js' });
    vm.runInContext(SRC, sandbox, { filename: 'toast.js' });
    vm.runInContext(GROUPING_SRC, sandbox, { filename: 'toast-grouping.js' });
    vm.runInContext(RENDER_SRC, sandbox, { filename: 'toast-view.js' });
    vm.runInContext(LIFECYCLE_SRC, sandbox, { filename: 'toast-lifecycle.js' });
    vm.runInContext(ROW_MENU_ICONS_SRC, sandbox, { filename: 'session-row-menu-icons.js' });
    if (!sandbox.ToastSessionGroup) {
        throw new Error(
            'toast-session-group.js did not export itself into the sandbox, so '
            + 'the manager would silently fall back to per-kind coalescing and '
            + 'every one-card-per-session assertion would measure nothing');
    }
    manager = window.ToastManager;
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
    return container.childNodes.filter((e) => e._cls.has('toast'));
}
export function overflow(container) {
    return container.childNodes.find((e) => e._cls.has('toast-overflow')) || null;
}


export function dismissAllRow(container) {
    return container.childNodes.find((e) => e._cls.has('toast-dismiss-all')) || null;
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
