
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

export type MicPhase = 'idle' | 'listening' | 'working' | 'message';

const STOP_GRACE_MS = 1200;
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

    function release(): void {
        if (grace) { clearTimeout(grace); grace = null; }
        if (watchdog) { clearTimeout(watchdog); watchdog = null; }
        const e = engine;
        engine = null;
        e?.abort();
    }

    function reset(): void {
        run += 1;
        release();
        ticket = null;
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

    function launch(queue: EngineStarter[], mine: number): void {
        const [starter, ...rest] = queue;
        if (!starter) return;
        const live = starter === deps.speech;
        let up = !live;
        const next = (why: 'blocked' | 'unavailable' | 'failed' | 'no_response') => {
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
            text: (all) => { if (mine === run) state.transcript = all; },
            end: (all) => { if (mine === run) finish(all); },
            error: (why) => { if (mine === run) next(why); },
        });
        if (live) watchdog = setTimeout(() => { if (mine === run && !up) next('no_response'); }, READY_MS);
        else {
            void deps.transcribeReady().then((ok) => { if (mine === run && !ok) fail('no_transcribe'); }, () => {});
        }
    }

    function start(): void {
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
        if (state.phase !== 'listening' || !engine) return;
        const mine = run;
        if (!state.live) state.phase = 'working';
        engine.stop();
        if (state.live) grace = setTimeout(() => { if (mine === run) finish(null); }, STOP_GRACE_MS);
    }

    return { state, start, done, cancel: reset, dismiss: reset };
}
