
export interface Stage {
    id: string;
    t0: number;
    t1: number;
    label: string;
    hz: number[];
}

export type ModemEvent =
    | { type: 'stage'; stage: Stage; index: number }
    | { type: 'end' }
    | { type: 'stop' }
    | { type: 'joined' };

export interface ModemCounters {
    plays: number;
    stops: number;
    stage: string | null;
    ended: boolean;
    state: string;
    sources: number;
    peak: number;
    enabled: boolean;
    start: number;
    pending?: boolean;
    blocked?: boolean;
    late?: number;
    joined?: number;
}

const DTMF: Record<string, [number, number]> = { 1: [697, 1209], 2: [697, 1336], 3: [697, 1477], 4: [770, 1209], 5: [770, 1336], 6: [770, 1477], 7: [852, 1209], 8: [852, 1336], 9: [852, 1477], 0: [941, 1336] };
export const NUMBER = '2125551994';
const T = { dial: 0.5, dtmfOn: 0.055, dtmfOff: 0.045, ring: 1.0, ringOff: 0.3, ans: 1.25, v8: 0.9, info0: 0.55, l1: 0.3, l2: 0.6, train: 1.7, tail: 0.3 };

export const STAGES: Stage[] = [];
let total = 0;
function add(id: string, d: number, label: string, hz: number[]): void {
    STAGES.push({ id, t0: total, t1: total + d, label, hz });
    total += d;
}
add('dialtone', T.dial, 'off-hook dial tone', [350, 440]);
add('dtmf', NUMBER.length * (T.dtmfOn + T.dtmfOff), 'DTMF dialing', [697, 770, 852, 941, 1209, 1336, 1477]);
add('ringback', T.ring + T.ringOff, 'ringback', [440, 480]);
add('ansam', T.ans, 'ANSam answer tone (V.8)', [2100]);
add('v8', T.v8, 'V.8 CM/JM exchange (V.21 FSK)', [980, 1180, 1650, 1850]);
add('info0', T.info0, 'V.34 phase 2 INFO0 (DPSK)', [1200, 2400]);
add('probe', T.l1 + T.l2, 'L1/L2 line probe (150 Hz comb)', Array.from({ length: 25 }, (_, i) => 150 * (i + 1)));
add('train', T.train, 'phase 3/4 training screech', []);
add('connect', T.tail, 'CONNECT 53333', []);
export const DURATION = total;

export function stage(id: string): Stage {
    return STAGES.find((s) => s.id === id) as Stage;
}

function lcg(seed: number): () => number {
    let s = seed >>> 0;
    return () => { s = (Math.imul(s, 1664525) + 1013904223) >>> 0; return s / 4294967296; };
}
function noiseBuf(ctx: BaseAudioContext, secs: number, seed: number): AudioBuffer {
    const sr = ctx.sampleRate;
    const n = Math.floor(sr * secs);
    const b = ctx.createBuffer(1, n, sr);
    const d = b.getChannelData(0);
    const r = lcg(seed);
    for (let i = 0; i < n; i++) d[i] = r() * 2 - 1;
    return b;
}

export function build(ctx: BaseAudioContext, dest: AudioNode, o: { t0?: number; gain?: number } = {}): { sources: AudioScheduledSourceNode[]; master: GainNode } {
    const T0 = o.t0 == null ? 0.05 : o.t0;
    const src: AudioScheduledSourceNode[] = [];
    const master = ctx.createGain();
    master.gain.value = o.gain == null ? 0.8 : o.gain;
    master.connect(dest);
    const track = <N extends AudioScheduledSourceNode>(n: N): N => { src.push(n); return n; };
    const gain = (v: number, to?: AudioNode | AudioParam): GainNode => {
        const g = ctx.createGain();
        g.gain.value = v;
        g.connect((to || master) as AudioNode);
        return g;
    };
    function burst(freqs: number[], a: number, b: number, amp: number, to?: AudioNode): GainNode {
        const g = ctx.createGain();
        g.gain.setValueAtTime(0, T0 + a);
        g.gain.linearRampToValueAtTime(amp, T0 + a + 0.004);
        g.gain.setValueAtTime(amp, T0 + b - 0.004);
        g.gain.linearRampToValueAtTime(0, T0 + b);
        g.connect(to || master);
        freqs.forEach((f) => {
            const os = track(ctx.createOscillator());
            os.frequency.value = f;
            os.connect(g);
            os.start(T0 + a);
            os.stop(T0 + b + 0.01);
        });
        return g;
    }
    const st = stage;
    burst([350, 440], st('dialtone').t0, st('dialtone').t1, 0.22);
    for (let i = 0; i < NUMBER.length; i++) {
        const a = st('dtmf').t0 + i * (T.dtmfOn + T.dtmfOff);
        burst(DTMF[NUMBER[i]!]!, a, a + T.dtmfOn, 0.26);
    }
    burst([440, 480], st('ringback').t0, st('ringback').t0 + T.ring, 0.2);
    const ck = track(ctx.createBufferSource());
    ck.buffer = noiseBuf(ctx, 0.03, 11);
    const ckg = gain(0, master);
    ckg.gain.setValueAtTime(0.5, T0 + st('ansam').t0 - 0.02);
    ckg.gain.linearRampToValueAtTime(0, T0 + st('ansam').t0);
    ck.connect(ckg);
    ck.start(T0 + st('ansam').t0 - 0.02);
    (() => {
        const a = st('ansam').t0;
        const b = st('ansam').t1;
        const car = track(ctx.createOscillator());
        const pol = ctx.createGain();
        const am = ctx.createGain();
        const env = ctx.createGain();
        const lfo = track(ctx.createOscillator());
        const lg = gain(0.2, am.gain);
        car.frequency.value = 2100;
        am.gain.value = 0.8;
        lfo.frequency.value = 15;
        lfo.connect(lg);
        pol.gain.setValueAtTime(1, T0 + a);
        for (let k = 1; T0 + a + k * 0.45 < T0 + b; k++) pol.gain.setValueAtTime(k % 2 ? -1 : 1, T0 + a + k * 0.45);
        env.gain.setValueAtTime(0, T0 + a);
        env.gain.linearRampToValueAtTime(0.3, T0 + a + 0.02);
        env.gain.setValueAtTime(0.3, T0 + b - 0.03);
        env.gain.linearRampToValueAtTime(0, T0 + b);
        car.connect(pol);
        pol.connect(am);
        am.connect(env);
        env.connect(master);
        car.start(T0 + a);
        lfo.start(T0 + a);
        car.stop(T0 + b + 0.02);
        lfo.stop(T0 + b + 0.02);
    })();
    function fsk(mark: number, space: number, a: number, b: number, amp: number, seed: number): void {
        const os = track(ctx.createOscillator());
        const g = ctx.createGain();
        const r = lcg(seed);
        const bit = 1 / 300;
        os.frequency.setValueAtTime(mark, T0 + a);
        for (let x = a, n = 0; x < b; x += bit, n++) os.frequency.setValueAtTime(n < 20 ? (n % 2 ? space : mark) : r() < 0.5 ? space : mark, T0 + x);
        g.gain.setValueAtTime(0, T0 + a);
        g.gain.linearRampToValueAtTime(amp, T0 + a + 0.004);
        g.gain.setValueAtTime(amp, T0 + b - 0.004);
        g.gain.linearRampToValueAtTime(0, T0 + b);
        os.connect(g);
        g.connect(master);
        os.start(T0 + a);
        os.stop(T0 + b + 0.01);
    }
    (() => {
        const a = st('v8').t0;
        fsk(980, 1180, a, a + 0.4, 0.24, 21);
        fsk(1650, 1850, a + 0.3, a + 0.7, 0.24, 22);
        fsk(980, 1180, a + 0.6, a + 0.9, 0.2, 23);
    })();
    function dpsk(fc: number, a: number, b: number, amp: number, seed: number): void {
        const os = track(ctx.createOscillator());
        const pol = ctx.createGain();
        const g = ctx.createGain();
        const r = lcg(seed);
        const bit = 1 / 600;
        let s = 1;
        os.frequency.value = fc;
        pol.gain.setValueAtTime(1, T0 + a);
        for (let x = a + bit; x < b; x += bit) {
            if (r() < 0.5) s = -s;
            pol.gain.setValueAtTime(s, T0 + x);
        }
        g.gain.setValueAtTime(0, T0 + a);
        g.gain.linearRampToValueAtTime(amp, T0 + a + 0.005);
        g.gain.setValueAtTime(amp, T0 + b - 0.005);
        g.gain.linearRampToValueAtTime(0, T0 + b);
        os.connect(pol);
        pol.connect(g);
        g.connect(master);
        os.start(T0 + a);
        os.stop(T0 + b + 0.01);
    }
    (() => {
        const a = st('info0').t0;
        dpsk(1200, a, a + 0.55, 0.22, 31);
        dpsk(2400, a + 0.08, a + 0.55, 0.2, 32);
    })();
    (() => {
        const a = st('probe').t0;
        const b = st('probe').t1;
        const pol = ctx.createGain();
        const env = ctx.createGain();
        pol.gain.setValueAtTime(1, T0 + a);
        for (let x = a + 0.1, s = 1; x < b; x += 0.1) {
            s = -s;
            pol.gain.setValueAtTime(s, T0 + x);
        }
        env.gain.setValueAtTime(0, T0 + a);
        env.gain.linearRampToValueAtTime(0.28, T0 + a + 0.01);
        env.gain.setValueAtTime(0.28, T0 + a + T.l1);
        env.gain.linearRampToValueAtTime(0.4, T0 + a + T.l1 + 0.02);
        env.gain.setValueAtTime(0.4, T0 + b - 0.01);
        env.gain.linearRampToValueAtTime(0, T0 + b);
        for (let f = 150; f <= 3750; f += 150) {
            const os = track(ctx.createOscillator());
            const tg = gain(1 / 25, pol);
            os.frequency.value = f;
            os.connect(tg);
            os.start(T0 + a);
            os.stop(T0 + b + 0.01);
        }
        pol.connect(env);
        env.connect(master);
    })();
    (() => {
        const a = st('train').t0;
        const b = st('train').t1;
        function band(seed: number, f0: number, f1: number, q: number, amp: number, a0: number): void {
            const nb = track(ctx.createBufferSource());
            nb.buffer = noiseBuf(ctx, b - a0 + 0.2, seed);
            const bp = ctx.createBiquadFilter();
            const g = ctx.createGain();
            bp.type = 'bandpass';
            bp.Q.value = q;
            bp.frequency.setValueAtTime(f0, T0 + a0);
            bp.frequency.linearRampToValueAtTime(f1, T0 + b);
            g.gain.setValueAtTime(0, T0 + a0);
            g.gain.linearRampToValueAtTime(amp, T0 + a0 + 0.08);
            g.gain.setValueAtTime(amp, T0 + b - 0.12);
            g.gain.linearRampToValueAtTime(0, T0 + b);
            nb.connect(bp);
            bp.connect(g);
            g.connect(master);
            nb.start(T0 + a0);
            nb.stop(T0 + b + 0.05);
        }
        band(41, 700, 1900, 0.9, 0.6, a);
        band(42, 3100, 1500, 0.8, 0.5, a + 0.3);
        band(43, 1800, 2600, 0.35, 0.3, a + 0.7);
        const os = track(ctx.createOscillator());
        const g = ctx.createGain();
        const r = lcg(44);
        os.frequency.value = 2400;
        const pol = ctx.createGain();
        pol.gain.setValueAtTime(1, T0 + a);
        for (let x = a + 0.02, s = 1; x < b; x += 0.02) {
            if (r() < 0.5) s = -s;
            pol.gain.setValueAtTime(s, T0 + x);
        }
        g.gain.setValueAtTime(0, T0 + a);
        g.gain.linearRampToValueAtTime(0.1, T0 + a + 0.25);
        g.gain.setValueAtTime(0.1, T0 + b - 0.1);
        g.gain.linearRampToValueAtTime(0, T0 + b);
        os.connect(pol);
        pol.connect(g);
        g.connect(master);
        os.start(T0 + a);
        os.stop(T0 + b + 0.02);
    })();
    return { sources: src, master };
}

interface Run {
    sources: AudioScheduledSourceNode[];
    master: GainNode;
    ctx: AudioContext;
    an: AnalyserNode | null;
}

const AC: typeof AudioContext | undefined = typeof window !== 'undefined' ? window.AudioContext || (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext : undefined;
let ctx: AudioContext | null = null;
let run: Run | null = null;
let listeners: ((e: ModemEvent) => void)[] = [];
let timers: ReturnType<typeof setTimeout>[] = [];
let join: (() => void) | null = null;
let gen = 0;
const C: ModemCounters = { plays: 0, stops: 0, stage: null, ended: false, state: 'idle', sources: 0, peak: 0, enabled: true, start: 0 };

export function counters(): ModemCounters {
    return C;
}

function emit(e: ModemEvent): void {
    listeners.slice().forEach((f) => {
        try {
            f(e);
        } catch (x) {
            console.error(x);
        }
    });
}

export function onEvent(fn: (e: ModemEvent) => void): () => void {
    listeners.push(fn);
    return () => { listeners = listeners.filter((f) => f !== fn); };
}

function reduced(): boolean {
    return typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export function enabled(): boolean {
    const on = !reduced();
    C.enabled = on;
    return on;
}

export function playing(): boolean {
    return !!run;
}

export function pending(): boolean {
    return !!C.pending;
}

export function nudge(): void {
    if (join) join();
}

function nudgeEv(): void {
    if (join) join();
}
function unarm(): void {
    join = null;
    removeEventListener('keydown', nudgeEv, true);
    removeEventListener('pointerdown', nudgeEv, true);
}

function sampleOf(my: Run): void {
    if (run !== my || !my.an) return;
    const d = new Uint8Array(my.an.fftSize);
    let p = 0;
    my.an.getByteTimeDomainData(d);
    for (let i = 0; i < d.length; i++) p = Math.max(p, Math.abs(d[i]! - 128));
    C.peak = Math.max(C.peak, p / 128);
}

function stageTimers(my: Run, off: number): void {
    STAGES.forEach((s, i) => {
        const d = Math.max(0, s.t0 * 1000 + 50 - off * 1000);
        if (s.t0 * 1000 + 50 < off * 1000 - 50 && i < STAGES.length - 1) return;
        timers.push(setTimeout(() => {
            if (run !== my) return;
            C.stage = s.id;
            emit({ type: 'stage', stage: s, index: i });
            sampleOf(my);
        }, d));
        timers.push(setTimeout(() => sampleOf(my), Math.max(0, (s.t0 + (s.t1 - s.t0) * 0.6) * 1000 + 50 - off * 1000)));
    });
    timers.push(setTimeout(() => {
        if (run !== my) return;
        C.ended = true;
        C.state = 'ended';
        const c = my.ctx;
        run = null;
        ctx = null;
        try { void c.close(); } catch {  }
        emit({ type: 'end' });
    }, Math.max(0, DURATION * 1000 + 120 - off * 1000)));
}

function joinLate(mine: AudioContext, t0: number): void {
    const sr = mine.sampleRate;
    const OAC = window.OfflineAudioContext || (window as unknown as { webkitOfflineAudioContext?: typeof OfflineAudioContext }).webkitOfflineAudioContext;
    let off: OfflineAudioContext;
    try {
        off = new OAC!(1, Math.ceil(sr * (DURATION + 0.4)), sr);
    } catch {
        return;
    }
    build(off, off.destination, { t0: 0.05 });
    void off.startRendering().then((buf) => {
        if (ctx !== mine) return;
        const el = (performance.now() - t0) / 1000;
        if (el >= DURATION) {
            C.state = 'ended';
            C.ended = true;
            ctx = null;
            try { void mine.close(); } catch {  }
            return;
        }
        const an = mine.createAnalyser();
        an.fftSize = 512;
        an.connect(mine.destination);
        const g = mine.createGain();
        const sc = mine.createBufferSource();
        sc.buffer = buf;
        sc.connect(g);
        g.connect(an);
        sc.start(0, el);
        run = { sources: [sc], master: g, ctx: mine, an };
        C.sources = 1;
        C.state = 'playing';
        C.joined = (C.joined || 0) + 1;
        C.late = el;
        stageTimers(run, el);
        emit({ type: 'joined' });
    });
}

export function play(force?: boolean): boolean {
    stop(true);
    if (!AC || (!force && !enabled())) return false;
    try {
        ctx = new AC();
    } catch {
        ctx = null;
        return false;
    }
    const mine = ctx;
    const t0 = performance.now();
    const cold = !force && !!navigator.userActivation && !navigator.userActivation.hasBeenActive;
    const my = ++gen;
    C.plays++;
    C.ended = false;
    C.start = t0;
    C.pending = false;
    C.late = 0;
    if (cold) {
        C.pending = true;
        C.blocked = true;
        C.state = 'waiting for a gesture';
        const go = (): void => {
            if (gen !== my || ctx !== mine || !C.pending) return;
            C.pending = false;
            unarm();
            joinLate(mine, t0);
        };
        join = () => { try { void mine.resume().then(go, () => {}); } catch {  } };
        addEventListener('keydown', nudgeEv, true);
        addEventListener('pointerdown', nudgeEv, true);
        try { void mine.resume().then(go, () => {}); } catch {  }
        return true;
    }
    if (ctx.state === 'suspended') void ctx.resume();
    const an = ctx.createAnalyser();
    an.fftSize = 512;
    an.connect(ctx.destination);
    const built = build(ctx, an, { t0: 0.05 });
    run = { ...built, ctx, an };
    C.sources = built.sources.length;
    C.state = 'playing';
    stageTimers(run, 0);
    return true;
}

export function stop(quiet?: boolean): boolean {
    timers.forEach(clearTimeout);
    timers = [];
    gen++;
    C.pending = false;
    unarm();
    if (!run) {
        if (ctx) {
            const pc = ctx;
            ctx = null;
            try { void pc.close(); } catch {  }
        }
        return false;
    }
    const r = run;
    const c = ctx as AudioContext;
    run = null;
    ctx = null;
    try {
        r.master.gain.cancelScheduledValues(0);
        r.master.gain.setTargetAtTime(0, c.currentTime, 0.002);
    } catch {  }
    r.sources.forEach((s) => { try { s.stop(); } catch {  } });
    setTimeout(() => { try { void c.close(); } catch {  } }, 30);
    C.stops++;
    C.state = 'stopped';
    if (!quiet) emit({ type: 'stop' });
    return true;
}

export function preview(): boolean {
    return play(true);
}
