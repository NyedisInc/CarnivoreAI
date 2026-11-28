
import { createKeepAwake, pageHidden } from './wake-lock';

export interface EngineEvents {
    text(all: string): void;
    ready(): void;
    end(all: string | null): void;
    error(reason: 'blocked' | 'unavailable' | 'failed'): void;
}

export interface Engine {
    stop(): void;
    abort(): void;
}

export type EngineStarter = (events: EngineEvents) => Engine;

export interface MicDeps {
    claim(): unknown;
    deliver(text: string, ticket: unknown): void;
    speech: EngineStarter | null;
    speechNeedsHttps?: boolean;
    record: EngineStarter | null;
    transcribeReady(): Promise<boolean>;
}

export function glueText(a: string, b: string): string {
    if (!a) return b;
    if (!b) return a;
    return /\s$/.test(a) || /^\s/.test(b) ? a + b : `${a} ${b}`;
}

export type MicPhase = 'idle' | 'listening' | 'working' | 'message';

const STOP_GRACE_MS = 1200;
const MAX_QUIET_RESTARTS = 5;
const QUIET_WINDOW_MS = 5000;
const READY_MS = 3000;

export function createMic(deps: MicDeps) {
    const state = $state<{ phase: MicPhase; transcript: string; live: boolean; reason: string }>({
        phase: 'idle', transcript: '', live: false, reason: '',
    });
    let engine: Engine | null = null;
    let ticket: unknown = null;
    let run = 0;
    let grace: ReturnType<typeof setTimeout> | null = null;
    let watchdog: ReturnType<typeof setTimeout> | null = null;
    let stopping = false;
    let prefix = '';
    let quiet = 0;
    let quietSince = 0;
    let lastStarter: EngineStarter | null = null;
    const awake = createKeepAwake();

    function release(): void {
        if (grace) { clearTimeout(grace); grace = null; }
        if (watchdog) { clearTimeout(watchdog); watchdog = null; }
        const e = engine;
        engine = null;
        e?.abort();
        awake.drop();
    }

    function reset(): void {
        run += 1;
        release();
        ticket = null;
        stopping = false;
        prefix = '';
        quiet = 0;
        state.phase = 'idle';
        state.transcript = '';
        state.reason = '';
    }

    function fail(reason: string): void {
        run += 1;
        release();
        ticket = null;
        state.transcript = '';
        state.reason = reason;
        state.phase = 'message';
    }

    function finish(text: string | null): void {
        const words = (text?.trim() || state.transcript).trim();
        const t = ticket;
        reset();
        if (!words) { state.reason = 'empty'; state.phase = 'message'; return; }
        deps.deliver(words, t);
    }

    function launch(queue: EngineStarter[], mine: number, resumed = false): void {
        const [starter, ...rest] = queue;
        if (!starter) return;
        const live = starter === deps.speech;
        let up = !live || resumed;
        lastStarter = starter;
        const next = (why: 'blocked' | 'unavailable' | 'failed' | 'no_response') => {
            if (up && live && why === 'failed' && state.transcript && !stopping) { restart(mine); return; }
            if (up || rest.length === 0) { fail(why); return; }
            const e = engine;
            engine = null;
            if (watchdog) { clearTimeout(watchdog); watchdog = null; }
            e?.abort();
            launch(rest, mine);
        };
        state.live = live;
        engine = starter({
            ready: () => { if (mine === run) { up = true; if (watchdog) { clearTimeout(watchdog); watchdog = null; } } },
            text: (all) => {
                if (mine !== run) return;
                if (all) quiet = 0;
                state.transcript = glueText(prefix, all);
            },
            end: (all) => {
                if (mine !== run) return;
                if (live && state.phase === 'listening' && !stopping) { restart(mine, all); return; }
                finish(all === null ? null : glueText(prefix, all));
            },
            error: (why) => { if (mine === run) next(why); },
        });
        awake.hold();
        if (live && !up) watchdog = setTimeout(() => { if (mine === run && !up) next('no_response'); }, READY_MS);
        else if (!live) {
            void deps.transcribeReady().then((ok) => { if (mine === run && !ok) fail('no_transcribe'); }, () => {});
        }
    }

    function restart(mine: number, final?: string | null): void {
        const heard = glueText(prefix, final ?? '');
        if (heard.length > state.transcript.length) state.transcript = heard;
        prefix = state.transcript;
        const e = engine;
        engine = null;
        if (watchdog) { clearTimeout(watchdog); watchdog = null; }
        e?.abort();
        if (pageHidden()) { awake.drop(); state.reason = 'paused'; return; }
        const now = Date.now();
        if (quiet === 0 || now - quietSince > QUIET_WINDOW_MS) { quiet = 0; quietSince = now; }
        quiet += 1;
        if (quiet >= MAX_QUIET_RESTARTS || !lastStarter) { awake.drop(); state.reason = 'dropping'; return; }
        launch([lastStarter], mine, true);
    }

    function retry(): void {
        if (state.phase !== 'listening' || engine || !lastStarter) return;
        state.reason = '';
        quiet = 0;
        launch([lastStarter], run, true);
    }

    function pause(): void {
        if (state.phase !== 'listening' || !engine) return;
        prefix = state.transcript;
        release();
        state.reason = 'paused';
    }
    if (typeof document !== 'undefined') document.addEventListener('visibilitychange', pause);

    function start(): void {
        if (state.phase === 'listening' && !engine) { retry(); return; }
        if (state.phase === 'listening' || state.phase === 'working') return;
        reset();
        const queue = [deps.speech, deps.record].filter((s): s is EngineStarter => s !== null);
        if (queue.length === 0) { fail(globalThis.isSecureContext === false ? 'insecure' : 'unavailable'); return; }
        const needsHttps = deps.speech === queue[0] ? deps.speechNeedsHttps !== false : true;
        if (globalThis.isSecureContext === false && needsHttps) { fail('insecure'); return; }
        ticket = deps.claim();
        const mine = ++run;
        state.phase = 'listening';
        launch(queue, mine);
    }

    function done(): void {
        if (state.phase !== 'listening') return;
        if (!engine) { finish(null); return; }
        stopping = true;
        const mine = run;
        if (!state.live) state.phase = 'working';
        engine.stop();
        if (state.live) grace = setTimeout(() => { if (mine === run) finish(null); }, STOP_GRACE_MS);
    }

    return { state, start, done, retry, cancel: reset, dismiss: reset };
}
