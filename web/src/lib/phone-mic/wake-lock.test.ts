import { afterEach, describe, expect, it, vi } from 'vitest';
import { createMic, type Engine, type EngineEvents } from './controller.svelte';

function fakeDocument() {
    const target = new EventTarget();
    const doc = Object.assign(target, { visibilityState: 'visible' });
    return { doc, setVisible(v: boolean) { doc.visibilityState = v ? 'visible' : 'hidden'; target.dispatchEvent(new Event('visibilitychange')); } };
}

function fakeWakeLock(refuse = false) {
    const log = { requests: 0, released: 0 };
    return { log, wakeLock: { request: async () => {
        log.requests += 1;
        if (refuse) throw new DOMException('refused', 'NotAllowedError');
        return Object.assign(new EventTarget(), { release: async () => { log.released += 1; } });
    } } };
}

function fakeEngine() {
    const probe: { events: EngineEvents | null; aborted: number } = { events: null, aborted: 0 };
    const engine: Engine = { stop: () => {}, abort: () => { probe.aborted += 1; } };
    return { probe, starter: (events: EngineEvents) => { probe.events = events; return engine; } };
}

const settle = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };

function setup(refuse = false) {
    const d = fakeDocument();
    const w = fakeWakeLock(refuse);
    vi.stubGlobal('document', d.doc);
    vi.stubGlobal('navigator', { wakeLock: w.wakeLock });
    const e = fakeEngine();
    const deliver = vi.fn();
    const mic = createMic({ claim: () => 't', deliver, speech: e.starter, record: null, transcribeReady: async () => true });
    return { d, w, e, deliver, mic };
}

afterEach(() => { vi.unstubAllGlobals(); });

describe('phone mic keeps the screen awake and survives a hidden page (#3092)', () => {
    it('takes the lock while listening, retakes it on visible, releases it on stop', async () => {
        const { w, mic, e } = setup();
        mic.start();
        await settle();
        expect(w.log.requests).toBe(1);
        mic.done();
        e.probe.events!.end('');
        await settle();
        expect(w.log.released).toBe(1);
        mic.start();
        await settle();
        expect(w.log.requests).toBe(2);
        mic.cancel();
        await settle();
        expect(w.log.released).toBe(2);
    });

    it('a coalesced hidden and visible pair still pauses a listening mic and keeps the words', async () => {
        const { d, mic, e } = setup();
        mic.start();
        await settle();
        e.probe.events!.text('kept words');
        d.setVisible(true);
        await settle();
        expect(e.probe.aborted).toBeGreaterThan(0);
        expect(mic.state.reason).toBe('paused');
        expect(mic.state.transcript).toBe('kept words');
    });

    it('a refused lock does not break the capture', async () => {
        const { w, mic, e } = setup(true);
        mic.start();
        await settle();
        e.probe.events!.text('still works');
        expect(w.log.requests).toBe(1);
        expect(mic.state.phase).toBe('listening');
        expect(mic.state.transcript).toBe('still works');
    });

    it('hidden while listening keeps the words, ends the engine, and the next tap listens again', async () => {
        const { d, w, mic, e, deliver } = setup();
        mic.start();
        await settle();
        e.probe.events!.text('half a thought');
        d.setVisible(false);
        await settle();
        expect(e.probe.aborted).toBeGreaterThan(0);
        expect(w.log.released).toBe(1);
        expect(mic.state.reason).toBe('paused');
        expect(mic.state.transcript).toBe('half a thought');
        e.probe.events!.end('');
        expect(mic.state.phase).toBe('listening');
        d.setVisible(true);
        mic.start();
        await settle();
        expect(mic.state.reason).toBe('');
        e.probe.events!.text('and the rest');
        expect(mic.state.transcript).toBe('half a thought and the rest');
        expect(w.log.requests).toBe(2);
        mic.done();
        e.probe.events!.end('and the rest');
        expect(deliver).toHaveBeenCalledWith('half a thought and the rest', 't');
    });

    it('hidden while paused and sent pastes the kept words', async () => {
        const { d, mic, deliver, e } = setup();
        mic.start();
        e.probe.events!.text('keep me');
        d.setVisible(false);
        mic.done();
        expect(deliver).toHaveBeenCalledWith('keep me', 't');
    });
});
