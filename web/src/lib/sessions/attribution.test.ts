/* list, so the with a plain */
import { describe, expect, test } from 'vitest';

import {
    buildWorkStampIndex,
    instanceKey,
    resolveSessionAttribution,
    sortRunningSessionsByWork,
    workStampFor,
} from './attribution';
import type { RunningSessionRow, SessionRecord } from './types';

function record(over: Partial<SessionRecord> = {}): SessionRecord {
    return {
        id: 1,
        tmux_name: 'cloude_a',
        tmux_created_epoch: 1000,
        project_id: 7,
        project_attribution: 'exact',
        archived_at: null,
        last_work_at: null,
        ...over,
    };
}

function row(over: Partial<RunningSessionRow> = {}): RunningSessionRow {
    return { name: 'cloude_a', created_by_cloude: true, created_at_epoch: 1000, ...over };
}

describe('the archived row must never shadow a live one sharing its name', () => {
    const newest = record({ id: 4, tmux_created_epoch: 1788016091, project_id: 4 });
    const archived = record({
        id: 3, tmux_created_epoch: 1787686975, project_id: 3,
        archived_at: '2026-09-01T00:00:00Z',
    });

    test.each([
        ['newest first, the server order', [newest, archived]],
        ['oldest first', [archived, newest]],
    ])('%s', (_label, rows) => {
        const { byName } = resolveSessionAttribution(rows as SessionRecord[]);
        expect(byName.get('cloude_a')?.id).toBe(4);
    });

    test('and the archived row is still reachable by its EXACT instance', () => {
        const { byInstance } = resolveSessionAttribution([newest, archived]);
        expect(byInstance.get(instanceKey('cloude_a', 1787686975))?.id).toBe(3);
        expect(byInstance.get(instanceKey('cloude_a', 1788016091))?.id).toBe(4);
    });
});

describe('ranking two live rows that share a name', () => {
    test('the newest epoch wins, whichever order they arrive in', () => {
        const older = record({ id: 1, tmux_created_epoch: 100 });
        const newer = record({ id: 2, tmux_created_epoch: 200 });
        expect(resolveSessionAttribution([older, newer]).byName.get('cloude_a')?.id).toBe(2);
        expect(resolveSessionAttribution([newer, older]).byName.get('cloude_a')?.id).toBe(2);
    });

    test('a TIE on the maximum is ambiguous, and is absent from byName', () => {
        const rows = [
            record({ id: 1, tmux_created_epoch: 200 }),
            record({ id: 2, tmux_created_epoch: 200 }),
            record({ id: 3, tmux_created_epoch: 100 }),
        ];
        const { byName, ambiguous } = resolveSessionAttribution(rows);
        expect(ambiguous.has('cloude_a')).toBe(true);
        expect(byName.has('cloude_a')).toBe(false);
    });

    test('a candidate with NO epoch cannot be ranked, so the whole name is', () => {
        const rows = [
            record({ id: 1, tmux_created_epoch: 200 }),
            record({ id: 2, tmux_created_epoch: null }),
        ];
        const { byName, ambiguous } = resolveSessionAttribution(rows);
        expect(ambiguous.has('cloude_a')).toBe(true);
        expect(byName.has('cloude_a')).toBe(false);
    });

    test('one candidate alone is never ambiguous, even with no epoch', () => {
        // NEGATIVE CONTROL for
        const { byName, ambiguous } = resolveSessionAttribution([
            record({ id: 9, tmux_created_epoch: null }),
        ]);
        expect(ambiguous.size).toBe(0);
        expect(byName.get('cloude_a')?.id).toBe(9);
    });
});

describe('the instance key', () => {
    test('is NUL separated, so no name can collide with another', () => {
        expect(instanceKey('a', 1)).toBe(['a', 1].join(String.fromCharCode(0)));
        expect(instanceKey('a-1', 2)).not.toBe(instanceKey('a', '1-2'));
    });

    test('a genuine collision drops the key rather than picking one', () => {
        const rows = [
            record({ id: 1, tmux_created_epoch: 500 }),
            record({ id: 2, tmux_created_epoch: 500 }),
        ];
        const { byInstance } = resolveSessionAttribution(rows);
        expect(byInstance.has(instanceKey('cloude_a', 500))).toBe(false);
    });

    test('a row with no epoch contributes no instance key at all', () => {
        const { byInstance } = resolveSessionAttribution([
            record({ tmux_created_epoch: null }),
        ]);
        expect(byInstance.size).toBe(0);
    });
});

describe('the work-stamp index', () => {
    test('takes the MAXIMUM per tmux name, not the last row seen', () => {
        const rows = [
            record({ id: 1, tmux_created_epoch: 100, last_work_at: '2026-09-01T00:00:00Z' }),
            record({ id: 2, tmux_created_epoch: 200, last_work_at: '2026-09-09T00:00:00Z' }),
            record({ id: 3, tmux_created_epoch: 300, last_work_at: '2026-09-05T00:00:00Z' }),
        ];
        expect(buildWorkStampIndex(rows).get('cloude_a')).toBe('2026-09-09T00:00:00Z');
    });

    test('INCLUDES archived rows, unlike the name-only join', () => {
        const rows = [
            record({ id: 1, last_work_at: '2026-09-01T00:00:00Z' }),
            record({
                id: 2, tmux_created_epoch: 200, archived_at: '2026-09-02T00:00:00Z',
                last_work_at: '2026-09-09T00:00:00Z',
            }),
        ];
        expect(buildWorkStampIndex(rows).get('cloude_a')).toBe('2026-09-09T00:00:00Z');
    });

    test('a row with no stamp contributes NOTHING, not a zero', () => {
        const index = buildWorkStampIndex([record({ last_work_at: null })]);
        expect(index.has('cloude_a')).toBe(false);
        expect(workStampFor(row(), index)).toBeNull();
    });

    test('a non-array payload yields an empty index rather than throwing', () => {
        expect(buildWorkStampIndex(null).size).toBe(0);
    });
});

describe('the running list is ordered by WORK, newest first', () => {
    const stamps = new Map([
        ['cloude_old', '2026-09-01T00:00:00Z'],
        ['cloude_mid', '2026-09-05T00:00:00Z'],
        ['cloude_new', '2026-09-09T00:00:00Z'],
    ]);

    test('newest work leads', () => {
        const rows = [
            row({ name: 'cloude_old' }),
            row({ name: 'cloude_new' }),
            row({ name: 'cloude_mid' }),
        ];
        expect(sortRunningSessionsByWork(rows, stamps).map((r) => r.name))
            .toEqual(['cloude_new', 'cloude_mid', 'cloude_old']);
    });

    test('SELECTING a row does not move it, which is the core assertion', () => {
        // timeline was destroyed by the act of reading it.
        const before = sortRunningSessionsByWork([
            row({ name: 'cloude_old' }),
            row({ name: 'cloude_new' }),
            row({ name: 'cloude_mid' }),
        ], stamps).map((r) => r.name);

        const after = sortRunningSessionsByWork([
            row({ name: 'cloude_old', is_active: true }),
            row({ name: 'cloude_new' }),
            row({ name: 'cloude_mid' }),
        ], stamps).map((r) => r.name);

        expect(after).toEqual(before);
    });

    test('UNRECORDED sorts last, and is NOT treated as work at the epoch', () => {
        const rows = [
            row({ name: 'cloude_none' }),
            row({ name: 'cloude_old' }),
        ];
        expect(sortRunningSessionsByWork(rows, stamps).map((r) => r.name))
            .toEqual(['cloude_old', 'cloude_none']);
    });

    test('unrecorded rows keep newest-created-first among themselves', () => {
        const rows = [
            row({ name: 'cloude_x', created_at_epoch: 100 }),
            row({ name: 'cloude_y', created_at_epoch: 300 }),
            row({ name: 'cloude_z', created_at_epoch: 200 }),
        ];
        expect(sortRunningSessionsByWork(rows, stamps).map((r) => r.name))
            .toEqual(['cloude_y', 'cloude_z', 'cloude_x']);
    });

    test('created_by_cloude breaks a tie BELOW the work key, never above it', () => {
        const rows = [
            row({ name: 'cloude_none', created_by_cloude: true }),
            row({ name: 'cloude_old', created_by_cloude: false }),
        ];
        expect(sortRunningSessionsByWork(rows, stamps)[0]!.name).toBe('cloude_old');

        const tied = [
            row({ name: 'cloude_p', created_by_cloude: false, created_at_epoch: 500 }),
            row({ name: 'cloude_q', created_by_cloude: true, created_at_epoch: 500 }),
        ];
        expect(sortRunningSessionsByWork(tied, stamps)[0]!.name).toBe('cloude_q');
    });

    test('a missing index leaves every row unrecorded rather than throwing', () => {
        const rows = [
            row({ name: 'cloude_a', created_at_epoch: 100 }),
            row({ name: 'cloude_b', created_at_epoch: 200 }),
        ];
        expect(sortRunningSessionsByWork(rows, null).map((r) => r.name))
            .toEqual(['cloude_b', 'cloude_a']);
    });
});
