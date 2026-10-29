import { expect, test } from 'vitest';
import { MAX_IN_FLIGHT, TimelineLanes, type TimelinePush, type TimelineReaders } from './timeline-lanes.svelte';
import type { SessionTimeline } from '../../opscenter/cells/timeline/types';

function fakeReaders() {
    const reads: string[] = [];
    const pending: { uuid: string; done: () => void }[] = [];
    const state = { inFlight: 0, max: 0 };
    const readers: TimelineReaders = {
        timeline: (uuid) => {
            reads.push(uuid);
            state.inFlight += 1;
            state.max = Math.max(state.max, state.inFlight);
            return new Promise<SessionTimeline>((resolve) => {
                pending.push({
                    uuid,
                    done: () => {
                        state.inFlight -= 1;
                        resolve({ session_uuid: uuid } as SessionTimeline);
                    },
                });
            });
        },
    };
    const settle = async (): Promise<void> => {
        for (const p of pending.splice(0)) p.done();
        await new Promise((r) => setTimeout(r, 0));
    };
    return { readers, reads, state, settle };
}

test('ten lanes load with at most four reads in flight, and a push re-reads only the lane it names', async () => {
    const fake = fakeReaders();
    let fire: (topics: string[]) => void = () => {};
    const push: TimelinePush = { onChange: (fn) => ((fire = fn), () => {}), isLive: () => true };
    const lanes = new TimelineLanes(fake.readers, push);
    lanes.start();
    const ids = Array.from({ length: 10 }, (_, i) => `u${i}`);
    ids.forEach((id, i) => {
        lanes.know(id, 100 + i);
        lanes.show(id, true);
    });
    lanes.know('off', 999);
    expect(fake.state.inFlight).toBe(MAX_IN_FLIGHT);
    for (let i = 0; i < 4; i += 1) await fake.settle();
    expect(fake.state.max).toBe(MAX_IN_FLIGHT);
    expect([...fake.reads].sort()).toEqual([...ids].sort());
    expect(ids.every((id) => lanes.lanes[id]?.status === 'ready')).toBe(true);

    fire(['session_timeline']);
    await fake.settle();
    await fake.settle();
    await fake.settle();
    expect(fake.reads).not.toContain('off');
    fake.reads.length = 0;

    fire(['bookmarks:103']);
    await fake.settle();
    expect(fake.reads).toEqual(['u3']);
    lanes.stop();
});
