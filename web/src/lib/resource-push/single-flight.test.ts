import { describe, expect, it } from 'vitest';

import { singleFlightWithRerun } from './single-flight';

function gated(): { run: () => Promise<void>; started: () => number; release: (n: number) => void } {
    const gates: Array<() => void> = [];
    let count = 0;
    return {
        run: () => new Promise<void>((resolve) => { count += 1; gates.push(resolve); }),
        started: () => count,
        release: (n) => gates[n]?.(),
    };
}

const flush = async (): Promise<void> => { for (let i = 0; i < 6; i += 1) await Promise.resolve(); };

describe('singleFlightWithRerun', () => {
    it('shares nothing when idle: one call, one run', async () => {
        const g = gated();
        const refresh = singleFlightWithRerun(g.run);
        const p = refresh();
        expect(g.started()).toBe(1);
        g.release(0);
        await p;
    });

    it('a call that arrives during a read waits for a read that STARTS after it (the write is in that one)', async () => {
        const g = gated();
        const refresh = singleFlightWithRerun(g.run);
        const first = refresh();
        const afterWrite = refresh();
        expect(g.started()).toBe(1);
        let settled = false;
        void afterWrite.then(() => { settled = true; });
        g.release(0);
        await first;
        await flush();
        expect(g.started()).toBe(2);
        expect(settled).toBe(false);
        g.release(1);
        await afterWrite;
        expect(settled).toBe(true);
    });

    it('any number of calls during one read share exactly ONE trailing read', async () => {
        const g = gated();
        const refresh = singleFlightWithRerun(g.run);
        const first = refresh();
        const a = refresh();
        const b = refresh();
        const c = refresh();
        g.release(0);
        await first;
        await flush();
        expect(g.started()).toBe(2);
        g.release(1);
        await Promise.all([a, b, c]);
        await flush();
        expect(g.started()).toBe(2);
    });

    it('a rejected run does not wedge the next call', async () => {
        let n = 0;
        const refresh = singleFlightWithRerun(async () => { n += 1; if (n === 1) throw new Error('x'); });
        await expect(refresh()).rejects.toThrow('x');
        await refresh();
        expect(n).toBe(2);
    });
});
