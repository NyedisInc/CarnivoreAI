import { describe, expect, test } from 'vitest';

import { oneShotReport, oneShotTargets } from './one-shot';
import type { RunningSessionRow } from '../sessions/types';

function row(extra: Partial<RunningSessionRow>): RunningSessionRow {
    return { name: 'cloude_x', ...extra } as RunningSessionRow;
}

describe('which sessions are offered', () => {
    test('a row with a session id and a recorded agent is offered', () => {
        const targets = oneShotTargets([
            row({ session_id: 'ses_a', agent_type: 'claude', label: 'api work' }),
        ]);
        expect(targets).toEqual([
            { sessionId: 'ses_a', label: 'api work', tmuxName: 'cloude_x', agent: 'claude' },
        ]);
    });

    test('a row with NO agent record is excluded', () => {
        expect(oneShotTargets([row({ session_id: 'ses_a' })])).toEqual([]);
    });

    test('a row with no session id is excluded: there is nothing to address', () => {
        expect(oneShotTargets([row({ agent_type: 'claude' })])).toEqual([]);
    });

    test('an AGENT RECORD OUTRANKS AN INFERENCE, and an inference still counts', () => {
        const targets = oneShotTargets([
            row({ session_id: 'a', agent_wrapper_label: 'wrapper', agent_type: 'claude' }),
            row({ session_id: 'b', agent_family: 'claude' }),
        ]);
        expect(targets.map((target) => target.agent)).toEqual(['wrapper', 'claude']);
    });

    test('an ADOPTED session is offered: its id is an id, not a tmux name', () => {
        const targets = oneShotTargets([
            row({ name: 'my_own', session_id: 'adopted:my_own', agent_type: 'codex' }),
        ]);
        expect(targets.map((target) => target.sessionId)).toEqual(['adopted:my_own']);
    });

    test('the label falls back to the tmux name and then to the id', () => {
        expect(oneShotTargets([row({ session_id: 'a', agent_type: 'c' })])[0]?.label).toBe(
            'cloude_x',
        );
        expect(
            oneShotTargets([row({ name: '', session_id: 'a', agent_type: 'c' })])[0]?.label,
        ).toBe('a');
    });

    test('an unreadable listing offers nothing rather than throwing', () => {
        expect(oneShotTargets(null)).toEqual([]);
        expect(oneShotTargets(undefined)).toEqual([]);
        expect(oneShotTargets([null as never])).toEqual([]);
    });

    test('NEGATIVE CONTROL: the filter can say yes', () => {
        expect(oneShotTargets([row({ session_id: 'a', agent_type: 'claude' })])).toHaveLength(1);
    });
});

describe('what the server measured', () => {
    test('three numbers, read exactly as they arrived', () => {
        expect(oneShotReport({ pasted_bytes: 120, stripped_count: 3, submitted: true })).toEqual({
            pastedBytes: 120,
            strippedCount: 3,
            submitted: true,
        });
    });

    test('A MEASURED ZERO IS NOT AN ABSENCE', () => {
        expect(oneShotReport({ stripped_count: 0 }).strippedCount).toBe(0);
    });

    test('`submitted: false` is a real outcome and is NOT null', () => {
        expect(oneShotReport({ submitted: false }).submitted).toBe(false);
    });

    test('a field the server did not send is null, and so is one of the wrong type', () => {
        expect(oneShotReport({})).toEqual({
            pastedBytes: null,
            strippedCount: null,
            submitted: null,
        });
        expect(oneShotReport({ pasted_bytes: 'lots', submitted: 'yes' }).pastedBytes).toBeNull();
        expect(oneShotReport({ submitted: 'yes' }).submitted).toBeNull();
    });

    test('a non-object answer reads as three nulls rather than throwing', () => {
        expect(oneShotReport(null).submitted).toBeNull();
        expect(oneShotReport('ok').pastedBytes).toBeNull();
    });
});
