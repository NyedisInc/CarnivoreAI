import { describe, expect, it } from 'vitest';
import { subagentChip, subagentCount, timerPlan } from './row-chips';
import type { SidebarRow } from './legacy';

function row(over: Record<string, unknown>): SidebarRow {
    return { name: 'a', ...over } as SidebarRow;
}

const NOT_A_COUNT: unknown[] = [null, undefined, 0, -3, Number.NaN, '2'];

describe('the subagent chip (cozy, #748)', () => {
    it('no chip for a null, absent, zero, negative or string count, or with no session id to open', () => {
        for (const value of NOT_A_COUNT) {
            expect(subagentChip(row({ session_id: 's', subagents_running: value })), String(value)).toBeNull();
        }
        expect(subagentChip(row({ subagents_running: 2 })), 'no id, nothing to open').toBeNull();
        expect(subagentChip(row({ session_id: 's', subagents_running: 2 }))?.attrs.class).toContain('subagent-count--button');
    });

    it('carries the catalog text, the sentence and the session id', () => {
        const chip = subagentChip(row({ session_id: 'ses_1', subagents_running: 2, subagents_total: 7 }))!;
        expect(chip.text).toBe('2 sub');
        expect(chip.attrs['aria-label']).toBe('2 subagents running, 7 launched in this conversation');
        expect(chip.attrs['data-subagents-session-id']).toBe('ses_1');
    });
});

describe('the bare subagent count (detailed, #848, #852)', () => {
    it('is a bare number with no chip class, and needs no session id', () => {
        for (const value of NOT_A_COUNT) {
            expect(subagentCount(row({ subagents_running: value })), String(value)).toBeNull();
        }
        const plain = subagentCount(row({ subagents_running: 2, subagents_total: 7 }))!;
        expect(plain.text).toBe('2');
        expect(plain.attrs).toEqual({ class: 'session-row__subagent-count' });
    });

    it('turns blue only while a workflow runs, on a strict true', () => {
        expect(subagentCount(row({ subagents_running: 2, workflow_active: true }))!.attrs.class)
            .toBe('session-row__subagent-count session-row__subagent-count--workflow');
        for (const value of [false, null, undefined, 'true', 1]) {
            expect(subagentCount(row({ subagents_running: 2, workflow_active: value }))!.attrs.class, String(value))
                .toBe('session-row__subagent-count');
        }
        expect(subagentCount(row({ subagents_running: 0, workflow_active: true })), 'no count, nothing to color').toBeNull();
    });
});

describe('the timer chip (#893)', () => {
    it('no chip for a non-positive or absent count, or with no session id to open', () => {
        for (const value of [null, undefined, 0, -1]) {
            expect(timerPlan(row({ session_id: 's', timers_live: value })), String(value)).toBeNull();
        }
        expect(timerPlan(row({ timers_live: 2 })), 'no id, nothing to open').toBeNull();
        expect(timerPlan(row({ session_id: 's', timers_live: 2 }))?.attrs.class).toContain('timer-chip--button');
    });

    it('carries the session id and a sentence naming the live count', () => {
        const chip = timerPlan(row({ session_id: 'ses_1', timers_live: 2 }))!;
        expect(chip.attrs['data-timers-session-id']).toBe('ses_1');
        expect(chip.attrs['aria-label']).toMatch(/2/);
        expect(chip.text).toMatch(/2/);
    });
});
