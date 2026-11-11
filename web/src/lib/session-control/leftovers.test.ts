import { beforeEach, describe, expect, it, vi } from 'vitest';

const authFetch = vi.fn();
vi.mock('../../opscenter/api/auth.svelte', () => ({
    authFetch: (...args: unknown[]) => authFetch(...args),
    ApiError: class ApiError extends Error {},
}));

import type { BackgroundProcess } from '../background-work/background-work';
import { leftoverRows, processText, stopLeftovers } from './control-center';

function proc(pid: number, ownerFinished: boolean | null): BackgroundProcess {
    return { pid, start: `start-${pid}`, task_id: `b${pid}`, started_at: null, children: 1, summary: 'until ! pgrep -f x', agent_id: 'a1', owner_finished: ownerFinished };
}

describe('leftover shells', () => {
    beforeEach(() => authFetch.mockReset());

    it('picks only rows whose owner finished, never an unmeasured one', () => {
        const rows = [proc(1, true), proc(2, false), proc(3, null)];
        expect(leftoverRows(rows).map((r) => r.pid)).toEqual([1]);
    });

    it('marks a leftover row and leaves other rows plain', () => {
        expect(processText(proc(1, true))).toContain('owner finished');
        expect(processText(proc(2, false))).toBe('until ! pgrep -f x');
    });

    it('posts the shown pairs to the stop-leftovers route', async () => {
        authFetch.mockResolvedValue({ results: [] });
        await stopLeftovers('ses_1', [proc(1, true)]);
        const [url, init] = authFetch.mock.calls[0];
        expect(url).toBe('/sessions/ses_1/background-work/stop-leftovers');
        expect(JSON.parse((init as { body: string }).body)).toEqual({ targets: [{ pid: 1, start: 'start-1' }] });
    });
});
