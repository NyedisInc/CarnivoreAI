
class Selector {
    constructor(text) {
        this.tag = null;
        this.id = null;
        this.classes = [];
        this.attrs = [];
        this.nots = [];
        this._parse(text.trim());
    }

    _parse(text) {
        text = text.replace(/:not\(([^)]*)\)/g, (_, inner) => {
            this.nots.push(new Selector(inner));
            return '';
        });
        const token = /([#.]?[A-Za-z0-9_-]+)|(\[[^\]]*\])/g;
        let m;
        while ((m = token.exec(text)) !== null) {
            const raw = m[0];
            if (raw[0] === '#') this.id = raw.slice(1);
            else if (raw[0] === '.') this.classes.push(raw.slice(1));
            else if (raw[0] === '[') {
                const body = raw.slice(1, -1);
                const eq = body.indexOf('=');
                if (eq === -1) this.attrs.push({ name: body, value: null });
                else {
                    this.attrs.push({
                        name: body.slice(0, eq),
                        value: body.slice(eq + 1).replace(/^["']|["']$/g, ''),
                    });
                }
            } else this.tag = raw.toLowerCase();
        }
    }

    matches(el) {
        if (this.tag && el.tagName.toLowerCase() !== this.tag) return false;
        if (this.id && el.getAttribute('id') !== this.id) return false;
        for (const c of this.classes) if (!el.classList.contains(c)) return false;
        for (const a of this.attrs) {
            const got = el.getAttribute(a.name);
            if (got === null || got === undefined) return false;
            if (a.value !== null && String(got) !== a.value) return false;
        }
        for (const n of this.nots) if (n.matches(el)) return false;
        return true;
    }
}

class ChainSelector {
    constructor(text) {
        this.parts = ChainSelector.splitCompounds(String(text).trim())
            .filter(Boolean)
            .map(p => new Selector(p));
    }

    static splitCompounds(text) {
        const out = [];
        let cur = '';
        let depth = 0;
        for (const ch of text) {
            if (ch === '[') depth++;
            else if (ch === ']') depth = depth > 0 ? depth - 1 : 0;
            if (depth === 0 && /\s/.test(ch)) {
                if (cur) { out.push(cur); cur = ''; }
                continue;
            }
            cur += ch;
        }
        if (cur) out.push(cur);
        return out;
    }

    matches(el) {
        if (this.parts.length === 0) return false;
        const last = this.parts[this.parts.length - 1];
        if (!last.matches(el)) return false;
        let i = this.parts.length - 2;
        let node = el.parentNode;
        while (i >= 0 && node) {
            if (this.parts[i].matches(node)) i--;
            node = node.parentNode;
        }
        return i < 0;
    }
}

function parseSelectorList(text) {
    return String(text).split(',')
        .map(s => s.trim())
        .filter(Boolean)
        .map(s => new ChainSelector(s));
}

class MiniTokenList {
    constructor(el) { this.el = el; }
    _tokens() {
        const v = this.el._attrs.get('class') || '';
        return v.split(/\s+/).filter(Boolean);
    }
    _write(tokens) { this.el._attrs.set('class', tokens.join(' ')); }
    contains(t) { return this._tokens().includes(t); }
    add(...ts) {
        const cur = this._tokens();
        for (const t of ts) if (!cur.includes(t)) cur.push(t);
        this._write(cur);
    }
    remove(...ts) { this._write(this._tokens().filter(t => !ts.includes(t))); }
    toggle(t, force) {
        const has = this.contains(t);
        const want = force === undefined ? !has : !!force;
        want ? this.add(t) : this.remove(t);
        return want;
    }
}

class MiniElement {
    constructor(tagName, doc) {
        this.tagName = tagName.toUpperCase();
        this.ownerDocument = doc;
        this.parentNode = null;
        this.childNodes = [];
        this._attrs = new Map();
        this._listeners = new Map();
        this.classList = new MiniTokenList(this);
        this.innerHTML = '';
        this.style = {
            setProperty(name, value) { this[name] = String(value); },
            getPropertyValue(name) {
                const v = this[name];
                return v === undefined ? '' : String(v);
            },
            removeProperty(name) { delete this[name]; },
        };
    }

    setAttribute(name, value) { this._attrs.set(name, String(value)); }
    getAttribute(name) {
        const v = this._attrs.get(name);
        return v === undefined ? null : v;
    }
    removeAttribute(name) { this._attrs.delete(name); }
    hasAttribute(name) { return this._attrs.has(name); }

    get id() { return this.getAttribute('id') || ''; }
    set id(v) { this.setAttribute('id', v); }

    get dataset() {
        const el = this;
        const attr = (k) => 'data-' + String(k).replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());
        return new Proxy({}, {
            get(_, k) { return typeof k === 'string' ? (el.getAttribute(attr(k)) ?? undefined) : undefined; },
            set(_, k, v) { el.setAttribute(attr(k), v); return true; },
        });
    }
    set dataset(v) {
        Object.defineProperty(this, 'dataset', { value: v, writable: true, configurable: true });
    }
    get className() { return this.getAttribute('class') || ''; }
    set className(v) { this.setAttribute('class', v); }
    get type() { return this.getAttribute('type') || ''; }
    set type(v) { this.setAttribute('type', v); }
    get hidden() { return this.hasAttribute('hidden'); }
    set hidden(v) { v ? this.setAttribute('hidden', '') : this.removeAttribute('hidden'); }
    get title() { return this.getAttribute('title') || ''; }
    set title(v) { this.setAttribute('title', v); }
    get id() { return this.getAttribute('id') || ''; }
    set id(v) { this.setAttribute('id', v); }

    get dataset() {
        const el = this;
        const attr = (k) => 'data-' + String(k).replace(/[A-Z]/g, (c) => '-' + c.toLowerCase());
        return new Proxy({}, {
            get(_, k) { return typeof k === 'string' ? (el.getAttribute(attr(k)) ?? undefined) : undefined; },
            set(_, k, v) { el.setAttribute(attr(k), v); return true; },
        });
    }
    set dataset(v) {
        Object.defineProperty(this, 'dataset', { value: v, writable: true, configurable: true });
    }

    get textContent() {
        let out = '';
        for (const c of this.childNodes) out += c.textContent;
        return out;
    }

    set textContent(v) {
        for (const c of this.childNodes.splice(0)) c.parentNode = null;
        if (v !== '' && v !== null && v !== undefined) {
            this.appendChild(this.ownerDocument.createTextNode(v));
        }
    }

    appendChild(node) {
        if (node.parentNode) node.parentNode.removeChild(node);
        node.parentNode = this;
        this.childNodes.push(node);
        return node;
    }

    insertBefore(node, ref) {
        if (!ref) return this.appendChild(node);
        if (node.parentNode) node.parentNode.removeChild(node);
        const i = this.childNodes.indexOf(ref);
        node.parentNode = this;
        this.childNodes.splice(i === -1 ? this.childNodes.length : i, 0, node);
        return node;
    }

    removeChild(node) {
        const i = this.childNodes.indexOf(node);
        if (i !== -1) this.childNodes.splice(i, 1);
        node.parentNode = null;
        return node;
    }

    remove() {
        if (this.parentNode) this.parentNode.removeChild(this);
        return this;
    }

    get children() { return this.childNodes.slice(); }

    get firstChild() { return this.childNodes[0] || null; }

    get lastChild() {
        return this.childNodes[this.childNodes.length - 1] || null;
    }

    contains(node) {
        for (let n = node; n; n = n.parentNode) if (n === this) return true;
        return false;
    }

    matches(selectorText) {
        return parseSelectorList(selectorText).some(s => s.matches(this));
    }

    closest(selectorText) {
        const list = parseSelectorList(selectorText);
        for (let n = this; n && n.tagName; n = n.parentNode) {
            if (list.some(s => s.matches(n))) return n;
        }
        return null;
    }

    _walk(out) {
        for (const c of this.childNodes) { out.push(c); c._walk(out); }
        return out;
    }

    querySelectorAll(selectorText) {
        const list = parseSelectorList(selectorText);
        return this._walk([]).filter(el => list.some(s => s.matches(el)));
    }

    querySelector(selectorText) {
        return this.querySelectorAll(selectorText)[0] || null;
    }

    addEventListener(type, fn) {
        if (!this._listeners.has(type)) this._listeners.set(type, []);
        this._listeners.get(type).push(fn);
    }

    removeEventListener(type, fn) {
        const arr = this._listeners.get(type) || [];
        const i = arr.indexOf(fn);
        if (i !== -1) arr.splice(i, 1);
    }

    _fire(type, event) {
        for (const fn of (this._listeners.get(type) || []).slice()) fn(event);
    }

    focus() { this.ownerDocument.activeElement = this; }

    dispatchEvent(type, extra = {}) {
        const event = Object.assign({
            type,
            target: this,
            defaultPrevented: false,
            _stopped: false,
            preventDefault() { this.defaultPrevented = true; },
            stopPropagation() { this._stopped = true; },
        }, extra);
        for (let n = this; n; n = n.parentNode) {
            n._fire(type, event);
            if (event._stopped) return event;
        }
        return event;
    }
}

class MiniText extends MiniElement {
    constructor(data, doc) {
        super('#text', doc);
        this._text = String(data);
    }
    get textContent() { return this._text; }
    set textContent(v) { this._text = String(v); }
}

class MiniDocument extends MiniElement {
    constructor() {
        super('#document', null);
        this.ownerDocument = this;
        this.readyState = 'complete';
        this.activeElement = null;
        this.documentElement = this.createElement('html');
        this.body = this.createElement('body');
        this.documentElement.appendChild(this.body);
        this.appendChild(this.documentElement);
    }

    createElement(tag) { return new MiniElement(tag, this); }

    createTextNode(data) { return new MiniText(data, this); }

    getElementById(id) {
        return this._walk([]).find(el => el.getAttribute('id') === id) || null;
    }
}

export function createEnvironment(options = {}) {
    const document = new MiniDocument();
    const mql = {
        matches: !!options.matches,
        _handlers: [],
        addEventListener(type, fn) { if (type === 'change') this._handlers.push(fn); },
        removeEventListener(type, fn) {
            const i = this._handlers.indexOf(fn);
            if (i !== -1) this._handlers.splice(i, 1);
        },
    };
    const window = {
        document,
        matchMedia() { return mql; },
        console,
        addEventListener() {},
    };
    window.window = window;

    return {
        window,
        document,
        mql,
        setMediaMatches(v) {
            mql.matches = !!v;
            for (const fn of mql._handlers.slice()) fn(mql);
        },
    };
}

export { MiniElement, MiniText, MiniDocument, Selector };
