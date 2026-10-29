
export interface Grid {
    w: number;
    h: number;
    ch: string[];
    fg: string[];
    bg: string[];
}

export interface HtmlOpts {
    limit?: number;
    rows?: number;
    skip?: (x: number, y: number) => boolean;
}

export interface FitOpts {
    max?: number;
    fill?: boolean;
    yboost?: number;
    center?: boolean;
}

export interface Mounted {
    wrap: HTMLElement;
    art: HTMLElement;
    grid: Grid;
    fit: () => number;
    redraw: (opts?: HtmlOpts) => void;
    ro?: ResizeObserver;
    destroy: () => void;
}

const X = '0123456789abcdef';

export const G = {
    full: '█', up: '▀', dn: '▄', lf: '▌', rt: '▐', l1: '░', l2: '▒', l3: '▓',
    sd: '┌┐└┘─│', dd: '╔╗╚╝═║', dot: '·', tri: '►', tri2: '◄', dia: '◆', ball: '●',
};

export function esc(c: string): string {
    return c === '<' ? '&lt;' : c === '&' ? '&amp;' : c === '>' ? '&gt;' : c;
}

export function escText(s: string): string {
    return String(s).replace(/[&<>]/g, esc);
}

export function html(g: Grid, o: HtmlOpts = {}): string {
    const rows = o.rows == null ? g.h : Math.min(g.h, o.rows);
    const limit = o.limit == null ? Infinity : o.limit;
    let out = '';
    let n = 0;
    for (let y = 0; y < rows; y++) {
        let run = '';
        let cf = -1;
        let cb = -1;
        let line = '';
        const flush = (): void => {
            if (!run) return;
            line += cf < 0 ? run : `<span class="f${X[cf]}${cb > 0 ? ` b${X[cb]}` : ''}">${run}</span>`;
            run = '';
        };
        for (let x = 0; x < g.w; x++) {
            let c = g.ch[y]!.charAt(x);
            let f = parseInt(g.fg[y]!.charAt(x), 16);
            let b = parseInt(g.bg[y]!.charAt(x), 16);
            if (n++ >= limit || (o.skip && o.skip(x, y))) {
                c = ' ';
                f = 0;
                b = 0;
            }
            const blank = c === ' ' && b === 0;
            const kf = blank ? -1 : f;
            const kb = blank ? 0 : b;
            if (kf !== cf || kb !== cb) {
                flush();
                cf = kf;
                cb = kb;
            }
            run += esc(c);
        }
        flush();
        out += `<div>${line}</div>`;
    }
    return out;
}

export function el(g: Grid, o: HtmlOpts = {}): HTMLElement {
    const d = document.createElement('div');
    d.className = 'ansi';
    d.setAttribute('aria-hidden', 'true');
    d.style.width = `${g.w * 8}px`;
    d.innerHTML = html(g, o);
    return d;
}

export function fit(wrap: HTMLElement, art: HTMLElement, g: Grid, o: FitOpts = {}): number {
    const max = o.max == null ? 2 : o.max;
    const nat = g.w * 8;
    const h = g.h * 16;
    const w = wrap.clientWidth || wrap.parentElement?.clientWidth || nat;
    let s = w / nat;
    if (o.fill) {
        const fx = Math.min(max, s);
        const fy = Math.max(0.125, Math.floor(fx * (o.yboost || 1) * 8) / 8);
        art.style.transform = `scale(${fx},${fy})`;
        wrap.style.height = `${Math.ceil(h * fy)}px`;
        art.style.left = '0';
        return fx;
    }
    s = s >= 1 ? Math.min(max, Math.max(1, Math.floor(s))) : s;
    art.style.transform = s === 1 ? 'none' : `scale(${s})`;
    wrap.style.height = `${Math.ceil(h * s)}px`;
    art.style.left = o.center !== false && s >= 1 ? `${Math.max(0, Math.floor((w - nat * s) / 2))}px` : '0';
    return s;
}

export interface MountOpts extends HtmlOpts {
    cls?: string;
    label?: string;
    max?: number;
    fill?: boolean;
    yboost?: number;
}

export function mount(host: HTMLElement, g: Grid, o: MountOpts = {}): Mounted {
    const wrap = document.createElement('div');
    wrap.className = `ansi-wrap${o.cls ? ` ${o.cls}` : ''}`;
    const art = el(g, o);
    wrap.appendChild(art);
    if (o.label) {
        const sr = document.createElement('span');
        sr.className = 'sr';
        sr.textContent = o.label;
        wrap.appendChild(sr);
    }
    host.appendChild(wrap);
    const api: Mounted = {
        wrap,
        art,
        grid: g,
        fit: () => fit(wrap, api.art, g, o),
        redraw: (oo) => { api.art.innerHTML = html(g, oo); },
        destroy: () => { api.ro?.disconnect(); },
    };
    api.fit();
    if (typeof ResizeObserver !== 'undefined') {
        let last = 0;
        api.ro = new ResizeObserver(() => {
            const w = wrap.clientWidth;
            if (w !== last) {
                last = w;
                api.fit();
            }
        });
        api.ro.observe(wrap);
    }
    return api;
}

export function blank(w: number, h: number): Grid {
    const ch: string[] = [];
    const fg: string[] = [];
    const bg: string[] = [];
    const r = ' '.repeat(Math.max(0, w));
    const z = '0'.repeat(Math.max(0, w));
    for (let i = 0; i < h; i++) {
        ch.push(r);
        fg.push(z);
        bg.push(z);
    }
    return { w, h, ch, fg, bg };
}

export function put(g: Grid, x: number, y: number, s: string, f?: number | null, b?: number | null): void {
    if (y < 0 || y >= g.h) return;
    for (let i = 0; i < s.length; i++) {
        const xx = x + i;
        if (xx < 0 || xx >= g.w) continue;
        g.ch[y]! = g.ch[y]!.slice(0, xx) + s.charAt(i) + g.ch[y]!.slice(xx + 1);
        if (f != null) g.fg[y]! = g.fg[y]!.slice(0, xx) + X[f]! + g.fg[y]!.slice(xx + 1);
        if (b != null) g.bg[y]! = g.bg[y]!.slice(0, xx) + X[b]! + g.bg[y]!.slice(xx + 1);
    }
}

export function fromPipe(src: string, w: number): Grid {
    const lines = src.split('\n');
    const g = blank(w, lines.length);
    lines.forEach((ln, y) => {
        let f = 7;
        let b = 0;
        let x = 0;
        let i = 0;
        while (i < ln.length) {
            const m = /^\|(\d\d)/.exec(ln.slice(i));
            if (m) {
                const n = +m[1]!;
                if (n < 16) f = n;
                else if (n < 24) b = n - 16;
                i += 3;
                continue;
            }
            put(g, x++, y, ln.charAt(i++), f, b);
        }
    });
    return g;
}

export interface BoxOpts {
    style?: 'single' | 'double' | 'shade';
    fg?: number;
    title?: string;
    titleFg?: number;
}

export function box(w: number, h: number, o: BoxOpts = {}): Grid {
    const g = blank(w, h);
    const s = o.style === 'double' ? G.dd : G.sd;
    const f = o.fg == null ? 3 : o.fg;
    if (o.style === 'shade') {
        for (let x = 0; x < w; x++) { put(g, x, 0, '▒', f, 0); put(g, x, h - 1, '▒', f, 0); }
        for (let y = 0; y < h; y++) { put(g, 0, y, '▓', f, 0); put(g, w - 1, y, '▓', f, 0); }
    } else {
        for (let x = 1; x < w - 1; x++) { put(g, x, 0, s.charAt(4), f); put(g, x, h - 1, s.charAt(4), f); }
        for (let y = 1; y < h - 1; y++) { put(g, 0, y, s.charAt(5), f); put(g, w - 1, y, s.charAt(5), f); }
        put(g, 0, 0, s.charAt(0), f); put(g, w - 1, 0, s.charAt(1), f); put(g, 0, h - 1, s.charAt(2), f); put(g, w - 1, h - 1, s.charAt(3), f);
    }
    if (o.title) put(g, 2, 0, ` ${o.title} `, o.titleFg == null ? 15 : o.titleFg);
    return g;
}
