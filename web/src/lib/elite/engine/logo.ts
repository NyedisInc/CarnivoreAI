import * as Ansi from './ansi';
import type { Grid } from './ansi';
import type { LogoPiece } from './logo-p1';
import { P1 } from './logo-p1';

export interface LogoOpts {
    baud?: number;
    pace?: number;
    phone?: boolean;
    still?: boolean;
    fit?: { max?: number; fill?: boolean; yboost?: number };
    label?: string;
    onRow?: (n: number, row: Element | undefined) => void;
    onDrips?: () => void;
    onGlitch?: () => void;
    onDone?: (why: string) => void;
}

export interface LogoApi {
    piece: LogoPiece;
    grid: LogoPiece;
    phase: 'draw' | 'drip' | 'glitch' | 'done';
    done: boolean;
    wrap: HTMLElement;
    art: HTMLElement;
    bbox: unknown;
    drips: [number, number, number][];
    skip: () => void;
    replay: () => void;
    still: () => void;
    fit: () => number;
    destroy: () => void;
}

export function reducedMotion(): boolean {
    return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

function pickGrid(p: LogoPiece, phone: boolean | undefined): LogoPiece {
    const isPhone = phone != null ? phone : window.innerWidth <= 800;
    return isPhone && p.phone ? { id: p.id, name: p.name, tag: p.tag, cuts: p.cuts, ...p.phone } : p;
}

export function baseGrid(g: LogoPiece): Grid {
    const G: Grid = { w: g.w, h: g.h, ch: g.ch.slice(), fg: g.fg.slice(), bg: g.bg.slice() };
    (g.dripCells || []).forEach((c) => {
        const [x, y] = c;
        G.ch[y]! = G.ch[y]!.slice(0, x) + c[2] + G.ch[y]!.slice(x + 1);
        G.fg[y]! = G.fg[y]!.slice(0, x) + c[3].toString(16) + G.fg[y]!.slice(x + 1);
        G.bg[y]! = G.bg[y]!.slice(0, x) + c[4].toString(16) + G.bg[y]!.slice(x + 1);
    });
    return G;
}

export function rowMs(g: Grid, baud?: number): number {
    return (g.w * 10) / (baud || 4800) * 1000;
}

export function draw(host: HTMLElement, o: LogoOpts = {}): LogoApi {
    const P = P1;
    const g = pickGrid(P, o.phone);
    const base = baseGrid(g);
    const baud = o.baud || 4800;
    const pace = o.pace || 1;
    let timers: ReturnType<typeof setTimeout>[] = [];
    let iv: ReturnType<typeof setInterval> | null = null;
    let fin = false;
    let drip: HTMLElement[] = [];
    const per = rowMs(g, baud) / pace;
    const m = Ansi.mount(host, base, { rows: 0, max: o.fit?.max != null ? o.fit.max : 2, fill: !!o.fit?.fill, yboost: o.fit?.yboost, label: o.label, cls: 'lg' });
    const api: LogoApi = {
        piece: P, grid: g, phase: 'draw', done: false, wrap: m.wrap, art: m.art, bbox: g.bbox, drips: g.drips || [],
        skip: () => { if (!fin) finish('skip'); },
        replay: () => { if (reducedMotion()) { still(); return; } run(); },
        still: () => still(),
        fit: m.fit,
        destroy: () => { clear(); m.destroy(); },
    };

    function later(fn: () => void, ms: number): void {
        timers.push(setTimeout(fn, ms / pace));
    }
    function resetRows(): void {
        [].slice.call(m.art.children).forEach((r: HTMLElement) => { r.style.transform = ''; });
    }
    function ghosts(on: boolean, dx?: number, which?: string): void {
        m.wrap.querySelectorAll('.lg-ghost').forEach((e) => e.remove());
        if (!on) return;
        const gl = Ansi.el(g);
        gl.className += ' lg-ghost';
        gl.dataset.ghost = which || 'a';
        gl.style.transform = `${m.art.style.transform && m.art.style.transform !== 'none' ? `${m.art.style.transform} ` : ''}translateX(${dx}px)`;
        gl.style.left = m.art.style.left;
        m.wrap.appendChild(gl);
    }
    function clear(): void {
        timers.forEach(clearTimeout);
        timers = [];
        if (iv) clearInterval(iv);
        iv = null;
        m.art.querySelectorAll('.lg-drip').forEach((d) => d.remove());
        resetRows();
        ghosts(false);
    }
    function paintRows(n: number): void {
        m.art.innerHTML = Ansi.html(base, { rows: n });
    }
    function finish(why: string): void {
        if (fin) return;
        fin = true;
        clear();
        m.art.innerHTML = Ansi.html(g);
        api.done = true;
        api.phase = 'done';
        o.onDone?.(why || 'done');
    }
    function still(): void {
        clear();
        m.art.innerHTML = Ansi.html(g);
        api.phase = 'done';
    }
    function glitch(): void {
        api.phase = 'glitch';
        o.onGlitch?.();
        const rowsEls = [].slice.call(m.art.children) as HTMLElement[];
        let seed = 7;
        const rnd = (): number => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; };
        const frames: [number, string][] = [[-6, 'a'], [5, 'b'], [-3, 'a']];
        frames.forEach((f, i) => {
            later(() => {
                resetRows();
                rowsEls.forEach((r) => { if (rnd() < 0.38) r.style.transform = `translateX(${Math.round((rnd() - 0.5) * 6) * 8}px)`; });
                ghosts(true, f[0], f[1]);
            }, i * 70);
        });
        later(() => { resetRows(); ghosts(false); }, 3 * 70);
        later(() => finish('done'), 3 * 70 + 120);
    }
    function dripPhase(): void {
        api.phase = 'drip';
        o.onDrips?.();
        const ds = g.drips || [];
        let DUR = 900;
        ds.forEach((d, i) => {
            const e = document.createElement('div');
            e.className = 'lg-drip';
            e.setAttribute('aria-hidden', 'true');
            e.style.cssText = `position:absolute;left:${d[0] * 8}px;top:${d[1] * 8}px;width:8px;height:${d[2] * 8}px;transform-origin:50% 0;transform:scaleY(0)`;
            m.art.appendChild(e);
            drip.push(e);
            const delay = (i % 7) * 70 + Math.floor(i / 7) * 25;
            const dur = 380 + d[2] * 70;
            e.animate?.([{ transform: 'scaleY(0)' }, { transform: 'scaleY(1)' }], { duration: dur / pace, delay: delay / pace, easing: 'cubic-bezier(.3,.1,.6,1)', fill: 'forwards' });
            DUR = Math.max(DUR, delay + dur);
        });
        later(() => {
            drip.forEach((e) => e.remove());
            drip = [];
            m.art.innerHTML = Ansi.html(g);
            glitch();
        }, Math.min(DUR, 2600) + 60);
        if (!ds.length) later(glitch, 120);
    }
    function run(): void {
        clear();
        fin = false;
        api.done = false;
        api.phase = 'draw';
        paintRows(0);
        const t0 = performance.now();
        let shown = 0;
        iv = setInterval(() => {
            const n = Math.min(g.h, Math.floor((performance.now() - t0) / per));
            if (n !== shown) {
                shown = n;
                paintRows(n);
                o.onRow?.(n, m.art.children[n - 1]);
            }
            if (n >= g.h) {
                if (iv) clearInterval(iv);
                iv = null;
                later(dripPhase, 140);
            }
        }, 33);
    }

    if (o.still || reducedMotion()) {
        still();
        fin = true;
        api.done = true;
        setTimeout(() => o.onDone?.('still'), 0);
    } else {
        run();
    }
    return api;
}
