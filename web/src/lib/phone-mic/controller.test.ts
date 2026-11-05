import { describe, expect, it, vi } from 'vitest';
import { createMic, type Engine, type EngineEvents } from './controller.svelte';

function fakeEngine() {
    const probe: { events: EngineEvents | null; stopped: boolean; aborted: boolean } = { events: null, stopped: false, aborted: false };
    const engine: Engine = { stop: () => { probe.stopped = true; }, abort: () => { probe.aborted = true; } };
    return { probe, starter: (events: EngineEvents) => { probe.events = events; return engine; } };
}

function setup() {
    const fake = fakeEngine();
    let live = 'ticket-1';
    const deliver = vi.fn();
    const claim = vi.fn(() => live);
    const mic = createMic({ claim, deliver, speech: fake.starter, record: null, transcribeReady: async () => true });
    return { fake, mic, deliver, claim, switchSession: () => { live = 'ticket-2'; } };
}

describe('phone mic controller', () => {
    it('a tap claims the target and listens at once', () => {
        const { mic, claim } = setup();
        mic.start();
        expect(mic.state.phase).toBe('listening');
        expect(claim).toHaveBeenCalledTimes(1);
    });

    it('done pastes the live transcript with the ticket claimed at the tap, no Enter', () => {
        const { fake, mic, deliver, switchSession } = setup();
        mic.start();
        fake.probe.events!.text('list the files');
        switchSession();
        mic.done();
        expect(fake.probe.stopped).toBe(true);
        fake.probe.events!.end('list the files');
        expect(deliver).toHaveBeenCalledWith('list the files', 'ticket-1');
        expect(String(deliver.mock.calls[0]?.[0])).not.toMatch(/[\r\n]/);
        expect(mic.state.phase).toBe('idle');
    });

    it('cancel discards and stops the engine', () => {
        const { fake, mic, deliver } = setup();
        mic.start();
        fake.probe.events!.text('never mind');
        mic.cancel();
        expect(fake.probe.aborted).toBe(true);
        expect(deliver).not.toHaveBeenCalled();
        expect(mic.state.phase).toBe('idle');
    });

    it('an engine that ends on its own pastes what it heard; silence says so', () => {
        const { fake, mic, deliver } = setup();
        mic.start();
        fake.probe.events!.end('hello');
        expect(deliver).toHaveBeenCalledWith('hello', 'ticket-1');
        mic.start();
        fake.probe.events!.end('');
        expect(deliver).toHaveBeenCalledTimes(1);
        expect(mic.state.reason).toBe('empty');
    });

    it('a blocked mic shows its reason and pastes nothing', () => {
        const { fake, mic, deliver } = setup();
        mic.start();
        fake.probe.events!.error('blocked');
        expect(mic.state.phase).toBe('message');
        expect(mic.state.reason).toBe('blocked');
        expect(deliver).not.toHaveBeenCalled();
    });

    it('records and transcribes when there is no live speech, and refuses without a transcribe connection', async () => {
        const fake = fakeEngine();
        const deliver = vi.fn();
        const mic = createMic({ claim: () => 't', deliver, speech: null, record: fake.starter, transcribeReady: async () => false });
        mic.start();
        await Promise.resolve();
        await Promise.resolve();
        expect(mic.state.reason).toBe('no_transcribe');
        expect(deliver).not.toHaveBeenCalled();
    });
});
