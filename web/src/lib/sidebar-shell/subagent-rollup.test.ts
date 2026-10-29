import { describe, expect, it } from 'vitest';
import { rollupHtml, runningOf } from './subagent-rollup';

describe('subagent rollup', () => {
    it('counts only positive integers', () => {
        expect(runningOf({ subagents_running: 2.9 })).toBe(2);
        expect(runningOf({ subagents_running: 0 })).toBeNull();
        expect(runningOf(null)).toBeNull();
    });
    it('sums a band once per session and draws nothing at zero', () => {
        const html = rollupHtml([
            { session_id: 'a', subagents_running: 2 }, { session_id: 'a', subagents_running: 2 }, { name: 'b', subagents_running: 1 },
        ]);
        expect(html).toContain('subagent-count--rollup');
        expect(html).toContain('3');
        expect(rollupHtml([{ name: 'c', subagents_running: 0 }])).toBe('');
    });
});
