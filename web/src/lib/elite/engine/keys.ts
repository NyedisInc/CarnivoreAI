
export interface Binding {
    combo: string;
    label: string;
    fn: (e: KeyEvent) => void;
    hidden: boolean;
    scope: string;
}

export interface KeyEvent {
    code: string;
    preventDefault: () => void;
    synthetic?: boolean;
    target?: EventTarget | null;
}

const reg: Record<string, Record<string, Binding>> = {};
const order: string[] = [];
let cur = 'main';
let catcher: ((e: KeyboardEvent) => void) | null = null;
let claims: (e: KeyboardEvent) => boolean = () => true;
let modalOpen: () => boolean = () => false;
let detach: (() => void) | null = null;

export function view(v?: string): string {
    if (v) cur = v;
    return cur;
}

export function catchAll(fn: ((e: KeyboardEvent) => void) | null): void {
    catcher = fn || null;
}

export function bind(scope: string | string[], combo: string, label: string, fn: (e: KeyEvent) => void, o?: { hidden?: boolean }): void {
    (Array.isArray(scope) ? scope : [scope]).forEach((sc) => {
        if (!reg[sc]) {
            reg[sc] = {};
            order.push(sc);
        }
        reg[sc][combo] = { combo, label: label || combo, fn, hidden: !!o?.hidden, scope: sc };
    });
}

export function unbind(scope: string, combo: string): void {
    if (reg[scope]) delete reg[scope][combo];
}

export function clear(scope?: string): void {
    if (scope) {
        delete reg[scope];
        return;
    }
    Object.keys(reg).forEach((k) => delete reg[k]);
    order.length = 0;
}

function comboOf(e: KeyboardEvent): string {
    return (e.ctrlKey ? 'ctrl+' : '') + (e.altKey ? 'alt+' : '') + (e.metaKey ? 'meta+' : '') + (e.shiftKey ? 'shift+' : '') + e.code;
}
function find(c: string): Binding | undefined {
    return reg[cur]?.[c] || reg.global?.[c];
}

export function fire(c: string): boolean {
    const b = find(c);
    if (!b) return false;
    b.fn({ preventDefault: () => {}, code: c, synthetic: true });
    return true;
}

const NAMES: Record<string, string> = {
    Space: 'Space', Enter: 'Enter', Slash: '/', 'shift+Slash': '?', Period: '.', Comma: ',', Minus: '-', Equal: '=', Backslash: '\\',
    Home: 'Home', End: 'End', Tab: 'Tab', ArrowLeft: 'Left', ArrowRight: 'Right', Backquote: '`', 'shift+Digit1': '!', 'shift+Equal': '+',
};
const CAPS: Record<string, string> = {
    Escape: 'esc', ArrowUp: 'up', ArrowDown: 'down', PageUp: 'pgup', PageDown: 'pgdn', Backspace: 'bksp', alt: 'alt', ctrl: 'ctrl', shift: 'shift', meta: 'cmd',
};

export function keyName(c: string, cap: (id: string) => string): string {
    if (NAMES[c]) return NAMES[c];
    return c.split('+').map((p) => (CAPS[p] ? cap(CAPS[p]) : NAMES[p] || p.replace(/^Key/, '').replace(/^Digit/, '').replace(/^Numpad/, 'n'))).join('+');
}

export interface HelpRow {
    combo: string;
    key: string;
    label: string;
}

export function helpModel(cap: (id: string) => string): { scope: string; current: boolean; rows: HelpRow[] }[] {
    const sec = (scope: string): { scope: string; current: boolean; rows: HelpRow[] } => ({
        scope,
        current: scope === cur,
        rows: Object.values(reg[scope] || {}).filter((b) => !b.hidden).map((b) => ({ combo: b.combo, key: keyName(b.combo, cap), label: b.label })),
    });
    return ['global', ...order.filter((s) => s !== 'global' && s !== 'modal')].map(sec).filter((s) => s.rows.length);
}

function typing(t: EventTarget | null): boolean {
    const el = t as HTMLElement | null;
    const n = (el?.tagName || '').toLowerCase();
    return n === 'input' || n === 'textarea' || n === 'select' || !!el?.isContentEditable;
}

function onKey(e: KeyboardEvent): void {
    if (e.isComposing || /^(Shift|Control|Alt|Meta|CapsLock)/.test(e.code)) return;
    if (!claims(e)) return;
    touch();
    if (catcher) {
        e.preventDefault();
        e.stopImmediatePropagation();
        catcher(e);
        return;
    }
    const c = comboOf(e);
    const t = e.target;
    if (modalOpen()) {
        const m = reg.modal?.[c];
        if (m) {
            e.preventDefault();
            m.fn(e);
        }
        return;
    }
    if (typing(t)) {
        if (c === 'Escape') {
            (t as HTMLElement).blur();
            e.preventDefault();
            const b1 = find('Escape');
            if (b1 && !(t as HTMLElement).hasAttribute('data-keep')) b1.fn(e);
            return;
        }
        if (!(e.ctrlKey || e.metaKey)) return;
    }
    const b = find(c);
    if (!b) return;
    e.preventDefault();
    b.fn(e);
}

export function attach(o: { claims: (e: KeyboardEvent) => boolean; modalOpen?: () => boolean }): () => void {
    claims = o.claims;
    modalOpen = o.modalOpen || (() => false);
    if (detach) detach();
    document.addEventListener('keydown', onKey, true);
    detach = () => {
        document.removeEventListener('keydown', onKey, true);
        detach = null;
        catcher = null;
    };
    return detach;
}

export function touch(): void {
    document.querySelectorAll('#elite-screen .cur').forEach((n) => {
        n.classList.remove('blink');
        void (n as HTMLElement).offsetWidth;
        n.classList.add('blink');
    });
}

export function cursor(el: HTMLElement): HTMLElement {
    el.classList.add('cur');
    el.classList.add('blink');
    return el;
}
