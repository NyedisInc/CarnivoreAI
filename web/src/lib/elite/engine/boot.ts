import * as Keys from './keys';
import * as Modem from './modem';
import { reducedMotion } from './logo';

export interface BootEvent {
    at: number;
    text: string;
    cls: string;
    cps: number;
    noise?: boolean;
    lazy?: () => string;
}

export interface BootText {
    atz: string;
    ok: string;
    dial: string;
    ring: string;
    monAnsam: string;
    monV8: string;
    monInfo0: string;
    monProbe: string;
    connect: string;
    ansi: string;
    handle: string;
    password: string;
    node: () => string;
}

export interface BootScript {
    events: BootEvent[];
    total: number;
}

const NOISE = '░▒▓█▀▄/\\|!?#%&*+~^=<>';
let seed = 7;
function rnd(): number {
    seed = (seed * 1103515245 + 12345) & 0x7fffffff;
    return seed / 0x7fffffff;
}
function noise(n: number): string {
    let s = '';
    for (let i = 0; i < n; i++) s += NOISE.charAt(Math.floor(rnd() * NOISE.length));
    return s;
}

export function script(tx: BootText): BootScript {
    seed = 7;
    const st = Modem.stage;
    const ev: BootEvent[] = [];
    const at = (t: number, text: string, cls: string, cps?: number, x?: Partial<BootEvent>): void => {
        ev.push({ at: t, text, cls, cps: cps || 90, ...(x || {}) });
    };
    at(0.0, tx.atz, 'd-cmd', 60);
    at(0.12, tx.ok, 'd-ok', 80);
    at(st('dtmf').t0, tx.dial, 'd-cmd', 17);
    at(st('ringback').t0 + 0.03, tx.ring, 'd-dim', 60);
    const M = (id: string, t: string): void => at(st(id).t0 + 0.04, t, 'd-dim', 150);
    M('ansam', tx.monAnsam);
    M('v8', tx.monV8);
    M('info0', tx.monInfo0);
    M('probe', tx.monProbe);
    const nz = (id: string, every: number, a: number, b: [number, number]): void => {
        const s = st(id);
        for (let t = s.t0 + a; t < s.t1 - 0.02; t += every) at(t, noise(Math.round(b[0] + rnd() * (b[1] - b[0]))), 'd-noise', 0, { noise: true });
    };
    nz('ansam', 0.15, 0.35, [20, 34]);
    nz('v8', 0.1, 0.15, [24, 40]);
    nz('info0', 0.08, 0.08, [30, 46]);
    nz('probe', 0.07, 0.1, [34, 52]);
    nz('train', 0.05, 0.03, [36, 52]);
    const c = st('connect').t0;
    at(c, tx.connect, 'd-con', 300);
    at(c + 0.12, tx.ansi, 'd-ans', 200);
    at(c + 0.25, tx.handle, 'd-cmd', 130);
    at(c + 0.4, tx.password, 'd-cmd', 120);
    at(c + 0.55, '', 'd-dim', 220, { lazy: tx.node });
    ev.sort((a, b) => a.at - b.at);
    return { events: ev, total: c + 0.9 };
}

function mkLine(host: HTMLElement, e: BootEvent): HTMLElement {
    const d = document.createElement('div');
    d.className = `d-line ${e.cls || ''}`;
    host.appendChild(d);
    while (host.children.length > 80) host.removeChild(host.firstChild as Node);
    host.scrollTop = host.scrollHeight;
    return d;
}

export function still(host: HTMLElement, sc: BootScript): void {
    host.innerHTML = '';
    sc.events.filter((e) => !e.noise).forEach((e) => {
        if (e.lazy) e.text = e.lazy();
        mkLine(host, e).textContent = e.text;
    });
    host.scrollTop = host.scrollHeight;
}

export interface BootRun {
    done: boolean;
    skip: () => void;
}

export function run(host: HTMLElement, sc: BootScript, o: { onLine?: (text: string) => void; onDone?: () => void } = {}): BootRun {
    host.innerHTML = '';
    const t0 = performance.now();
    let i = 0;
    let live: { e: BootEvent; el: HTMLElement; tn: Text; n: number }[] = [];
    let fin = false;
    const api: BootRun = { done: false, skip: () => { if (fin) return; still(host, sc); finish(); } };
    function finish(): void {
        if (fin) return;
        fin = true;
        clearInterval(iv);
        api.done = true;
        o.onDone?.();
    }
    const iv = setInterval(() => {
        if (fin) return;
        const now = (performance.now() - t0) / 1000;
        while (i < sc.events.length && sc.events[i]!.at <= now) {
            const e = sc.events[i++]!;
            if (e.lazy) e.text = e.lazy();
            const el = mkLine(host, e);
            const tn = document.createTextNode(e.noise ? e.text : '');
            el.appendChild(tn);
            live.push({ e, el, tn, n: 0 });
        }
        live.forEach((L) => {
            if (L.e.noise || L.n >= L.e.text.length) return;
            const n = Math.min(L.e.text.length, Math.floor((now - L.e.at) * L.e.cps));
            if (n !== L.n) {
                L.n = n;
                L.tn.data = L.e.text.slice(0, n);
                if (n >= L.e.text.length) o.onLine?.(L.e.text);
            }
        });
        live = live.filter((L) => (L.e.noise ? false : L.n < L.e.text.length));
        if (now >= sc.total && i >= sc.events.length && !live.length) finish();
    }, 33);
    return api;
}


export type HintKind = 'skip' | 'cold' | 'redial';

export interface CeremonyOpts {
    stage: HTMLElement;
    dial: HTMLElement;
    splash: HTMLElement;
    text: () => BootText;
    hangupText: () => { nocarrier: string; ath: string; hint: string };
    splashFn: (host: HTMLElement, o: { done: () => void; still: boolean }) => { skip: () => void } | null;
    onHint: (kind: HintKind) => void;
    onLive: (what: 'dialing' | 'welcome' | 'ready' | 'nocarrier' | 'line', text?: string) => void;
    hold?: number;
    direct?: boolean;
    onStart?: () => void;
    onDone?: (why: string) => void;
    onHangup?: () => void;
    onBack?: () => void;
}

export let active = false;

let last: CeremonyOpts | null = null;
let bootApi: BootRun | null = null;
let splApi: { skip: () => void } | null = null;
let offHint: (() => void) | null = null;
let timers: ReturnType<typeof setTimeout>[] = [];
let sound = false;
let stageClick: ((e: MouseEvent) => void) | null = null;

function hint(): void {
    if (!last) return;
    last.onHint(Modem.pending() ? 'cold' : sound || !Modem.enabled() ? 'skip' : 'redial');
}
function later(fn: () => void, ms: number): void {
    timers.push(setTimeout(fn, ms));
}
function clearTimers(): void {
    timers.forEach(clearTimeout);
    timers = [];
}

function end(why: string): void {
    if (!active) return;
    active = false;
    clearTimers();
    Keys.catchAll(null);
    Modem.stop();
    if (bootApi && !bootApi.done) bootApi.skip();
    if (splApi && splApi.skip) splApi.skip();
    bootApi = splApi = null;
    if (last) {
        last.stage.hidden = true;
        if (stageClick) last.stage.removeEventListener('click', stageClick);
    }
    stageClick = null;
    last?.onLive('ready');
    last?.onDone?.(why);
}

function catcher(e: KeyboardEvent): void {
    if (Modem.pending() && e.code !== 'Escape') {
        Modem.nudge();
        return;
    }
    end('key');
}

export function skip(): void {
    end('skip');
}

export function start(o: CeremonyOpts): boolean {
    clearTimers();
    last = o;
    const sc = script(o.text());
    if (o.direct || reducedMotion()) {
        active = false;
        o.stage.hidden = true;
        o.onDone?.('direct');
        return false;
    }
    o.dial.hidden = false;
    o.splash.hidden = true;
    o.dial.innerHTML = '';
    o.splash.innerHTML = '';
    o.stage.hidden = false;
    active = true;
    o.onStart?.();
    stageClick = (e: MouseEvent): void => {
        if ((e.target as Element | null)?.closest?.('.snd-btn, .boot-back')) return;
        if (Modem.pending()) {
            Modem.nudge();
            return;
        }
        end('click');
    };
    o.stage.addEventListener('click', stageClick);
    Keys.catchAll(catcher);
    sound = Modem.play();
    hint();
    if (offHint) offHint();
    offHint = Modem.onEvent((e) => {
        if (e.type === 'joined' && active) hint();
    });
    o.onLive('dialing');
    bootApi = run(o.dial, sc, {
        onLine: (t) => o.onLive('line', t),
        onDone: () => {
            if (!active) return;
            later(() => {
                if (!active) return;
                o.dial.hidden = true;
                o.splash.hidden = false;
                o.onLive('welcome');
                splApi = o.splashFn(o.splash, {
                    still: false,
                    done: () => {
                        if (!active) return;
                        later(() => end('done'), o.hold == null ? 600 : o.hold);
                    },
                });
            }, 120);
        },
    });
    return true;
}

export function replay(): void {
    if (!last) return;
    if (active) end('replay');
    start(last);
}

export function hangup(): void {
    if (!last) return;
    const o = last;
    if (active) end('hangup');
    Modem.stop();
    clearTimers();
    const tx = o.hangupText();
    o.stage.hidden = false;
    o.splash.hidden = true;
    o.dial.hidden = false;
    o.dial.innerHTML = '';
    [[tx.nocarrier, 'd-con'], [tx.ath, 'd-dim'], [tx.hint, 'd-dim']].forEach(([text, cls]) => {
        const d = document.createElement('div');
        d.className = `d-line ${cls}`;
        d.textContent = text ?? '';
        o.dial.appendChild(d);
    });
    active = true;
    o.onLive('nocarrier');
    o.onHangup?.();
    Keys.catchAll((e) => {
        active = false;
        Keys.catchAll(null);
        if (e.code === 'Escape') {
            o.onBack?.();
            return;
        }
        later(() => replay(), 0);
    });
}

export function destroy(): void {
    clearTimers();
    if (bootApi && !bootApi.done) bootApi.skip();
    if (splApi && splApi.skip) splApi.skip();
    bootApi = splApi = null;
    active = false;
    Keys.catchAll(null);
    Modem.stop();
    if (offHint) offHint();
    offHint = null;
    if (last && stageClick) last.stage.removeEventListener('click', stageClick);
    stageClick = null;
}
