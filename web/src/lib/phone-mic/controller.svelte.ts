
export interface EngineEvents {
    text(all: string): void;
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
    record: EngineStarter | null;
    transcribeReady(): Promise<boolean>;
}

export type MicPhase = 'idle' | 'listening' | 'working' | 'message';

const STOP_GRACE_MS = 1200;

export function createMic(deps: MicDeps) {
    const state = $state<{ phase: MicPhase; transcript: string; live: boolean; reason: string }>({
        phase: 'idle', transcript: '', live: false, reason: '',
    });
    let engine: Engine | null = null;
    let ticket: unknown = null;
    let run = 0;
    let grace: ReturnType<typeof setTimeout> | null = null;

    function release(): void {
        if (grace) { clearTimeout(grace); grace = null; }
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
        const words = (text ?? state.transcript).trim();
        const t = ticket;
        reset();
        if (!words) { state.reason = 'empty'; state.phase = 'message'; return; }
        deps.deliver(words, t);
    }

    function start(): void {
        if (state.phase === 'listening' || state.phase === 'working') return;
        reset();
        const starter = deps.speech ?? deps.record;
        if (!starter) { fail(window.isSecureContext ? 'unavailable' : 'insecure'); return; }
        ticket = deps.claim();
        const mine = ++run;
        const live = starter === deps.speech;
        state.live = live;
        state.phase = 'listening';
        engine = starter({
            text: (all) => { if (mine === run) state.transcript = all; },
            end: (all) => { if (mine === run) finish(all); },
            error: (why) => { if (mine === run) fail(why); },
        });
        if (!live) {
            void deps.transcribeReady().then((ok) => { if (mine === run && !ok) fail('no_transcribe'); }, () => {});
        }
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
