import { blank, box, el, fromPipe, put, type Grid } from './ansi';

const F3: Record<string, string> = {
    a: '010101111101101', b: '110101110101110', c: '011100100100011', d: '110101101101110', e: '111100110100111', f: '111100110100100', g: '011100101101011', h: '101101111101101', i: '111010010010111',
    j: '001001001101010', k: '101101110101101', l: '100100100100111', m: '101111111101101', n: '110101101101101', o: '010101101101010', p: '110101110100100', q: '010101101111011', r: '110101110101101',
    s: '011100010001110', t: '111010010010010', u: '101101101101111', v: '101101101101010', w: '101101111111101', x: '101101010101101', y: '101101010010010', z: '111001010100111',
    0: '111101101101111', 1: '010110010010111', 2: '110001010100111', 3: '110001010001110', 4: '101101111001001', 5: '111100110001110', 6: '011100111101111', 7: '111001010010010', 8: '111101111101111', 9: '111101111001110',
    ':': '000010000010000', '-': '000000111000000', '/': '001001010100100', '.': '000000000000010', '#': '101111101111101', '!': '010010010000010', '?': '110001010000010', '[': '110100100100110', ']': '011001001001011', '(': '010100100100010', ')': '010001001001010', '*': '101010111010101', ' ': '000000000000000',
};

export function overlay(b: Grid, x: number, y: number, g: Grid): Grid {
    for (let j = 0; j < g.h; j++) {
        for (let i = 0; i < g.w; i++) {
            const c = g.ch[j]!.charAt(i);
            const bgc = g.bg[j]!.charAt(i);
            if (c === ' ' && bgc === '0') continue;
            const xx = x + i;
            const yy = y + j;
            if (xx < 0 || yy < 0 || xx >= b.w || yy >= b.h) continue;
            b.ch[yy]! = b.ch[yy]!.slice(0, xx) + c + b.ch[yy]!.slice(xx + 1);
            b.fg[yy]! = b.fg[yy]!.slice(0, xx) + g.fg[j]!.charAt(i) + b.fg[yy]!.slice(xx + 1);
            b.bg[yy]! = b.bg[yy]!.slice(0, xx) + bgc + b.bg[yy]!.slice(xx + 1);
        }
    }
    return b;
}

export function label(text: string, o: { fg?: number; sh?: number; shadow?: boolean } = {}): Grid {
    const fg = o.fg == null ? 15 : o.fg;
    const sh = o.shadow === false ? null : o.sh == null ? 8 : o.sh;
    const t = String(text).toLowerCase();
    const g = blank(t.length * 4 + 1, 6);
    for (let k = 0; k < t.length; k++) {
        const gl = (F3[t.charAt(k)] || F3['?'])!;
        for (let p = 0; p < 15; p++) {
            if (gl.charAt(p) !== '1') continue;
            if (sh != null) put(g, k * 4 + (p % 3) + 1, Math.floor(p / 3) + 1, '░', sh, 0);
        }
    }
    for (let k = 0; k < t.length; k++) {
        const gl = (F3[t.charAt(k)] || F3['?'])!;
        for (let p = 0; p < 15; p++) if (gl.charAt(p) === '1') put(g, k * 4 + (p % 3), Math.floor(p / 3), '█', fg, 0);
    }
    return g;
}

export function strip1(w: number, title: string, o: { fg?: number; tag?: string } = {}): Grid {
    const g = blank(w, 1);
    const fg = o.fg == null ? 4 : o.fg;
    const t = ` ${title} `;
    put(g, 0, 0, '░▒▓█▓▒░', fg, 0);
    let x = 8;
    put(g, x, 0, t, 15, 0);
    x += t.length;
    put(g, x, 0, '░▒▓█▓▒░', fg, 0);
    x += 8;
    const tag = o.tag ? ` ${o.tag} ` : '';
    for (let i = x; i < w - tag.length; i++) put(g, i, 0, '─', 8, 0);
    if (tag) put(g, w - tag.length, 0, tag, 7, 0);
    return g;
}

export function drip(w: number, o: { seed?: number; len?: number } = {}): Grid {
    const g = blank(w, o.len ? o.len + 1 : 3);
    let seed = o.seed || 7;
    const r = (): number => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
    for (let x = 0; x < w; x++) put(g, x, 0, x % 5 === 2 ? '▓' : '▀', x % 3 ? 7 : 8, 0);
    for (let x = 1; x < w - 1; x += 3 + Math.floor(r() * 5)) {
        const ln = 1 + Math.floor(r() * (g.h - 1));
        for (let y = 1; y <= ln && y < g.h; y++) put(g, x, y, y === ln ? '▄' : '█', y === ln ? 14 : 10, 0);
    }
    return g;
}

export function dither(w: number, o: { fg?: number } = {}): Grid {
    const g = blank(w, 1);
    const fg = o.fg != null ? o.fg : 8;
    const pat = '░▒▓▒';
    for (let x = 0; x < w; x++) put(g, x, 0, pat.charAt(x % 4), fg, 0);
    return g;
}

export function frame(w: number, h: number, o: { style?: 'double' | 'heavy' | 'claw' | 'single'; title?: string; fg?: number } = {}): Grid {
    const st = o.style || 'double';
    const g = box(w, h, { style: st === 'heavy' ? 'shade' : st === 'single' ? 'single' : 'double', fg: o.fg == null ? 4 : o.fg, title: o.title, titleFg: 15 });
    if (st === 'claw') {
        const c = 10;
        put(g, 0, 0, '\\\\', c, 0); put(g, 0, 1, '\\', c, 0); put(g, w - 2, 0, '//', c, 0); put(g, w - 1, 1, '/', c, 0);
        put(g, 0, h - 1, '//', c, 0); put(g, 0, h - 2, '/', c, 0); put(g, w - 2, h - 1, '\\\\', c, 0); put(g, w - 1, h - 2, '\\', c, 0);
    }
    return g;
}

export function fangs(w: number, o: { dir?: 'down' | 'up'; fg?: number } = {}): Grid {
    const g = blank(w, 2);
    const up = o.dir === 'up';
    const fg = o.fg == null ? 15 : o.fg;
    for (let x = 0; x < w; x++) {
        put(g, x, up ? 1 : 0, x % 2 ? '█' : '▀', x % 6 < 3 ? 7 : 8, 0);
        if (x % 4 === 1) put(g, x, up ? 0 : 1, up ? '▲' : '▼', fg, 0);
    }
    return g;
}

export function skull(): Grid {
    return fromPipe('|15 ▄███▄ \n|15█|00▀|15█|00▄|15█|00▀|15█\n|15█ ▀█▀ █\n|15 ▀███▀ \n|08  ▀▄▀  ', 7);
}

export function live(host: HTMLElement, fn: (cols: number) => Grid): { redraw: () => void; destroy: () => void } {
    let last = -1;
    const draw = (): void => {
        const w = host.clientWidth;
        if (!w) return;
        const cols = Math.max(4, Math.floor(w / 8));
        if (cols === last) return;
        last = cols;
        const g = fn(cols);
        host.innerHTML = '';
        const a = el(g);
        a.style.position = 'relative';
        a.style.width = 'auto';
        a.style.whiteSpace = 'pre';
        a.style.overflow = 'hidden';
        a.style.maxWidth = '100%';
        host.appendChild(a);
        host.style.height = `${g.h * 16}px`;
    };
    host.classList.add('art-live');
    host.setAttribute('aria-hidden', 'true');
    draw();
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(draw) : null;
    ro?.observe(host);
    return { redraw: () => { last = -1; draw(); }, destroy: () => ro?.disconnect() };
}
