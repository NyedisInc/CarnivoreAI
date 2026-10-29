import { describe, expect, test } from 'vitest';

import { isArchived, rowIdOf, visibleRecentRows, type RecentRow } from './recent-visibility';

function ids(rows: readonly RecentRow[]): Array<number | string | null | undefined> {
    return rows.map((r) => r.id);
}

describe('the regression: a name is not an identity', () => {
    test('an archived row is kept when a live session reused its tmux name', () => {
        const recent: RecentRow[] = [
            { id: 9, tmux_name: 'cloude_Mac', archived_at: '2026-09-03T19:20:11.638508Z' },
            { id: 10, tmux_name: 'cloude_Hirschfeld', archived_at: '2026-09-03T19:20:11.685805Z' },
            { id: 41, tmux_name: 'cloude_CloudeCode', archived_at: '2026-09-07T13:31:01.049755Z' },
        ];
        const live = [
            { name: 'cloude_Mac', session_row_id: 11 },
            { name: 'cloude_Hirschfeld', session_row_id: 12 },
        ];
        expect(ids(visibleRecentRows(recent, live))).toEqual([9, 10, 41]);
    });

    test('a live row is never excluded on a name match alone', () => {
        const recent: RecentRow[] = [{ id: 30, tmux_name: 'cloude_BHPP', archived_at: null }];
        const live = [{ name: 'cloude_BHPP', session_row_id: 31 }];
        expect(ids(visibleRecentRows(recent, live))).toEqual([30]);
    });
});

describe('the guard still does its job, on identity', () => {
    test('a stopped row the reaper has not caught up with is suppressed', () => {
        const recent: RecentRow[] = [
            { id: 20, tmux_name: 'cloude_BHPP', archived_at: null },
            { id: 21, tmux_name: 'cloude_Other', archived_at: null },
        ];
        expect(ids(visibleRecentRows(recent, [{ name: 'cloude_BHPP', session_row_id: 20 }])))
            .toEqual([21]);
    });
});

describe('degraded identity is named, not silent', () => {
    test('with no session_row_id anywhere, the name key is used for live rows', () => {
        const recent: RecentRow[] = [
            { id: 40, tmux_name: 'cloude_BHPP', archived_at: null },
            { id: 41, tmux_name: 'cloude_Keep', archived_at: null },
        ];
        expect(ids(visibleRecentRows(recent, [{ name: 'cloude_BHPP' }]))).toEqual([41]);
    });

    test('with no session_row_id anywhere, an archived row is STILL kept', () => {
        const recent: RecentRow[] = [
            { id: 42, tmux_name: 'cloude_BHPP', archived_at: '2026-09-07T21:30:00.000000Z' },
        ];
        expect(ids(visibleRecentRows(recent, [{ name: 'cloude_BHPP' }]))).toEqual([42]);
    });

    test('a PARTIAL payload does not demote the whole list to the name key', () => {
        const recent: RecentRow[] = [{ id: 50, tmux_name: 'cloude_BHPP', archived_at: null }];
        const live = [{ name: 'cloude_BHPP' }, { name: 'cloude_Elsewhere', session_row_id: 99 }];
        expect(ids(visibleRecentRows(recent, live))).toEqual([50]);
    });
});

describe('shapes that must not throw and must not silently empty the list', () => {
    test('no live sessions excludes nothing', () => {
        const recent: RecentRow[] = [{ id: 60, tmux_name: 'cloude_A', archived_at: null }];
        expect(ids(visibleRecentRows(recent, []))).toEqual([60]);
        expect(ids(visibleRecentRows(recent, null))).toEqual([60]);
    });

    test('non-array inputs answer with an empty list, never a throw', () => {
        expect(visibleRecentRows(null, null)).toEqual([]);
        expect(visibleRecentRows(undefined, [{ name: 'x' }])).toEqual([]);
    });

    test('a row with no id survives an identity-keyed pass', () => {
        const recent: RecentRow[] = [{ tmux_name: 'cloude_A', archived_at: null }];
        expect(visibleRecentRows(recent, [{ name: 'cloude_A', session_row_id: 7 }]))
            .toHaveLength(1);
    });

    test('the filter returns a NEW array and mutates neither input', () => {
        const recent: RecentRow[] = [{ id: 1, archived_at: null }];
        const live = [{ name: 'x', session_row_id: 2 }];
        const out = visibleRecentRows(recent, live);
        expect(out).not.toBe(recent);
        expect(recent).toHaveLength(1);
        expect(live).toHaveLength(1);
    });
});

describe('the two helpers, stated rather than inferred', () => {
    test('rowIdOf normalises every "no id" shape to null', () => {
        expect(rowIdOf({ session_row_id: 11 })).toBe(11);
        expect(rowIdOf({ session_row_id: '11' })).toBe(11);
        expect(rowIdOf({ session_row_id: null })).toBeNull();
        expect(rowIdOf({ session_row_id: 0 })).toBeNull();
        expect(rowIdOf({})).toBeNull();
        expect(rowIdOf(null)).toBeNull();
    });

    test('isArchived reads archived_at and nothing else', () => {
        expect(isArchived({ archived_at: '2026-09-03T00:00:00Z' })).toBe(true);
        expect(isArchived({ archived_at: null })).toBe(false);
        expect(isArchived({ tmux_name: 'cloude_x' })).toBe(false);
        expect(isArchived(null)).toBe(false);
    });
});

describe('NEGATIVE CONTROL: the filter is capable of excluding something', () => {
    test('a matcher that always kept everything would pass every case above', () => {
        const recent: RecentRow[] = [{ id: 1, tmux_name: 'cloude_A', archived_at: null }];
        expect(visibleRecentRows(recent, [{ name: 'cloude_A', session_row_id: 1 }]))
            .toEqual([]);
    });
});
