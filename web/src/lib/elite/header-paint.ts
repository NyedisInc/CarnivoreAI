import * as Ansi from './engine/ansi';
import * as Art from './engine/art';

export interface Seg {
    c: string;
    k: number;
}

export function fitCol(s: string, n: number, right = false): string {
    const v = String(s);
    if (v.length > n) return n > 1 ? `${v.slice(0, n - 1)}…` : v.slice(0, n);
    const p = ' '.repeat(n - v.length);
    return right ? p + v : v + p;
}

export function barRuns(k: number, n = 10): [number, number] {
    const f = Math.max(0, Math.min(n, k));
    return [f, n - f];
}

function ramp(txt: string, from: number, to: number): Seg[] {
    const n = txt.length;
    return txt.split('').map((c, i) => ({ c, k: n < 2 ? from : Math.round(from + ((to - from) * i) / (n - 1)) }));
}

export function titleSegs(t: string, cells: number): Seg[] {
    let L = t.split('').join(' ');
    const RI = '░▒▓█';
    const RO = '█▓▒░';
    let g = Math.min(4, Math.floor((cells - L.length - 2) / 2));
    if (g < 1) {
        L = t;
        g = Math.min(4, Math.floor((cells - L.length - 2) / 2));
    }
    if (g < 1) return ramp(L, 1, 4);
    let fill = cells - (L.length + 2 + 2 * g);
    if (g < 4) fill = 0;
    const pat = '░▒░▒░▒▒░';
    const shade: Seg[] = [];
    for (let i = 0; i < fill; i++) shade.push({ c: pat.charAt(i % pat.length), k: 6 });
    return [...ramp(RI.slice(4 - g), 6, 3), { c: ' ', k: 6 }, ...ramp(L, 1, 4), { c: ' ', k: 6 }, ...ramp(RO.slice(0, g), 3, 6), ...shade];
}

export function cellsOf(pnl: HTMLElement): number {
    const cs = getComputedStyle(pnl);
    return Math.floor((pnl.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight)) / 8);
}

export function boxFrame(box: HTMLElement, style: 'double' | 'single', fg: number, title?: string, extra?: (g: Ansi.Grid, w: number, h: number) => void): () => void {
    const fr = box.querySelector<HTMLElement>('.m1h-fr');
    if (!fr) return () => {};
    box.style.minHeight = '0';
    const hpx = Math.ceil(box.clientHeight / 16) * 16;
    box.style.minHeight = `${hpx}px`;
    const w = Math.floor(box.clientWidth / 8);
    const h = Math.floor(hpx / 16);
    if (w < 8 || h < 3 || !box.clientWidth) return () => fr.replaceChildren();
    const g = Art.frame(w, h, { style, fg, title });
    extra?.(g, w, h);
    return () => fr.replaceChildren(Ansi.el(g));
}

export function callersExtras(g: Ansi.Grid, w: number, h: number): void {
    if (h < 10) return;
    Art.overlay(g, 1, h - 5, Art.dither(w - 2, { fg: 1 }));
    Art.overlay(g, 1, h - 4, Art.fangs(w - 2, { dir: 'up', fg: 15 }));
}

export function menuFrame(nav: HTMLElement, layer: HTMLElement): () => void {
    if (!nav.clientWidth) return () => layer.replaceChildren();
    const w = Math.floor(nav.clientWidth / 8);
    const h = Math.floor(nav.clientHeight / 16);
    if (w < 20 || h < 4) return () => layer.replaceChildren();
    const g = Art.frame(w, h, { style: 'double', fg: 4 });
    const pl = Array.from(nav.querySelectorAll<HTMLElement>('.hd-panel'));
    const hy: Record<number, 1> = {};
    const vx: [number, number, number][] = [];
    const jn: Record<string, [number, number]> = {};
    pl.forEach((pn) => {
        const y = Math.round(pn.offsetTop / 16);
        const x = Math.round(pn.offsetLeft / 8);
        if (y > 0 && y < h - 1) hy[y] = 1;
        if (x > 0 && x < w - 1) vx.push([x, y, Math.min(h, Math.round((pn.offsetTop + pn.offsetHeight) / 16))]);
    });
    Object.keys(hy).forEach((k) => {
        const y = +k;
        Ansi.put(g, 0, y, '╠', 4, 0);
        for (let x = 1; x < w - 1; x++) Ansi.put(g, x, y, '═', 4, 0);
        Ansi.put(g, w - 1, y, '╣', 4, 0);
    });
    vx.forEach(([x, y0, y1]) => {
        for (let y = y0; y < y1 && y < h; y++) {
            if (y > 0 && y < h - 1 && hy[y]) Ansi.put(g, x, y, '╬', 4, 0);
            else if (y !== 0 && y !== h - 1) Ansi.put(g, x, y, '║', 4, 0);
        }
        const J = (y: number, up: number, dn: number): void => {
            const k = `${y}:${x}`;
            const c = (jn[k] = jn[k] || [0, 0]);
            if (up) c[0] = 1;
            if (dn) c[1] = 1;
        };
        if (y0 === 0 || hy[y0]) J(y0, 0, 1);
        if (y1 >= h || hy[y1]) J(y1 >= h ? h - 1 : y1, 1, 0);
    });
    Object.keys(jn).forEach((k) => {
        const p = k.split(':');
        const c = jn[k]!;
        Ansi.put(g, +p[1]!, +p[0]!, c[0] && c[1] ? '╬' : c[0] ? '╩' : '╦', 4, 0);
    });
    return () => layer.replaceChildren(Ansi.el(g));
}
