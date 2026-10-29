/* could not determine */
import { describe, expect, test } from 'vitest';

import { emptyListing } from './listing';
import { filterDeadPanes, mergeLiveSession, mergeLiveSessions, rowsFromAttachable } from './running';
import type { RunningSessionRow, SessionListItem } from './types';

function stale(over: Partial<RunningSessionRow> = {}): RunningSessionRow {
    return {
        name: 'cloude_a',
        status: 'idle',
        unread: false,
        created_by_cloude: true,
        created_at_epoch: 1000,
        window_count: 1,
        agent_family: 'claude',
        agent_family_source: 'launched',
        agent_wrapper_label: 'claude in chrome',
        startup_gate: 'awaiting_startup_prompt',
        status_source: 'hook',
        activity_hint: 'shell',
        label: 'an old name',
        session_row_id: 7,
        parent_session_id: 'ses_parent',
        pinned_theme: 'amber',
        parked_summary: 'a stale parked task',
        usage_limit: { kind: 'session', resets_at: 'later', message: 'limit', since: 'now' } as unknown as RunningSessionRow['usage_limit'],
        host_state: 'offline',
        ...over,
    };
}

function live(over: Partial<SessionListItem> = {}): SessionListItem {
    return {
        tmux_session: 'cloude_a',
        activity_status: 'working',
        unread: true,
        created_by_cloude: true,
        session: { id: 'ses_live' },
        ...over,
    };
}

describe('the wrapper-versus-nested trap', () => {
    test('the session id is read off `.session`, not off the wrapper', () => {
        const rows = [stale()];
        mergeLiveSession(rows, live());
        expect(rows[0]!.session_id).toBe('ses_live');
    });

    test('a live-only row is built with the same rule', () => {
        const rows: RunningSessionRow[] = [];
        mergeLiveSession(rows, live({ tmux_session: 'cloude_new' }));
        expect(rows[0]!.session_id).toBe('ses_live');
    });

    test('a row with no tmux_session cannot be addressed and is skipped', () => {
        const rows: RunningSessionRow[] = [];
        expect(mergeLiveSession(rows, live({ tmux_session: null }))).toBe(false);
        expect(rows).toHaveLength(0);
    });
});

describe('the six fields a live row overwrites UNCONDITIONALLY', () => {
    const CASES: Array<[keyof RunningSessionRow, Partial<SessionListItem>]> = [
        ['agent_family', { agent_family: null }],
        ['agent_family_source', { agent_family_source: null }],
        ['agent_wrapper_label', { agent_wrapper_label: null }],
        ['status_source', { status_source: null }],
        ['activity_hint', { activity_hint: null }],
        ['session_row_id', { session_row_id: null }],
        ['parent_session_id', { parent_session_id: null }],
        ['parked_summary', { parked_summary: null }],
        ['usage_limit', { usage_limit: null }],
        ['host_state', { host_state: null }],
    ];

    test.each(CASES)('a null %s replaces the stale value on an existing row', (field, patch) => {
        const rows = [stale()];
        mergeLiveSession(rows, live(patch));
        expect(rows[0]![field]).toBeNull();
    });

    const UNSHIFT_CASES = CASES;

    test.each(UNSHIFT_CASES)('...and lands as null on a live-only row too', (field, patch) => {
        const rows: RunningSessionRow[] = [];
        mergeLiveSession(rows, live({ ...patch, tmux_session: 'cloude_new' }));
        expect(rows[0]![field]).toBeNull();
    });

    test('a live-only row carries the status provenance and the activity hint', () => {
        const rows: RunningSessionRow[] = [];
        mergeLiveSession(rows, live({
            status_source: 'registry', activity_hint: 'shell', tmux_session: 'cloude_new',
        }));
        expect(rows[0]!.status_source).toBe('registry');
        expect(rows[0]!.activity_hint).toBe('shell');
    });

    test('a live-only row with NO status_source claims none, rather than a guess', () => {
        const rows: RunningSessionRow[] = [];
        mergeLiveSession(rows, live({ status_source: undefined, tmux_session: 'cloude_new' }));
        expect(rows[0]!.status_source).toBeUndefined();
    });

    test('an ABSENT field also becomes null, so a stale guess cannot survive', () => {
        // could not determine
        const rows = [stale()];
        mergeLiveSession(rows, {
            tmux_session: 'cloude_a', activity_status: 'working', session: { id: 'x' },
        });
        expect(rows[0]!.agent_family).toBeNull();
        expect(rows[0]!.agent_family_source).toBeNull();
        expect(rows[0]!.agent_wrapper_label).toBeNull();
        expect(rows[0]!.status_source).toBeUndefined();
        expect(rows[0]!.activity_hint).toBeNull();
    });

    test('a session that has ANSWERED its trust prompt stops asking for a key', () => {
        const rows = [stale()];
        mergeLiveSession(rows, live({ startup_gate: 'ready' }));
        expect(rows[0]!.startup_gate).toBe('ready');
    });

    test('and a gate the server stopped sending stops being claimed', () => {
        const rows = [stale()];
        mergeLiveSession(rows, live({ startup_gate: undefined }));
        expect(rows[0]!.startup_gate).toBeUndefined();
    });

    test('a wrapper deleted mid-session stops being named', () => {
        const rows = [stale()];
        mergeLiveSession(rows, live({ agent_wrapper_label: null, agent_family: null }));
        expect(rows[0]!.agent_wrapper_label).toBeNull();
        expect(rows[0]!.agent_family).toBeNull();
    });

    test('the LABEL is overwritten when sent, including with an empty string', () => {
        const rows = [stale()];
        mergeLiveSession(rows, live({ label: '' }));
        expect(rows[0]!.label).toBe('');
    });

    test('...but an ABSENT label leaves the attachable row\'s own name alone', () => {
        const rows = [stale()];
        mergeLiveSession(rows, live({ label: undefined }));
        expect(rows[0]!.label).toBe('an old name');
    });

    test('the wrapper-level status is replaced, never OR-ed', () => {
        const rows = [stale({ status: 'working' })];
        mergeLiveSession(rows, live({ activity_status: 'idle' }));
        expect(rows[0]!.status).toBe('idle');
    });

    test('a live row that sends NO status reads unknown, not the stale one', () => {
        const rows = [stale({ status: 'working' })];
        mergeLiveSession(rows, live({ activity_status: null }));
        expect(rows[0]!.status).toBe('unknown');
    });

    test('NEGATIVE CONTROL: a real value does reach the row', () => {
        const rows = [stale()];
        mergeLiveSession(rows, live({
            agent_family: 'codex', agent_family_source: 'inferred_process',
            agent_wrapper_label: 'codex cli', status_source: 'transcript',
            startup_gate: 'ready', label: 'a new name', session_row_id: 42,
        }));
        expect(rows[0]).toMatchObject({
            agent_family: 'codex',
            agent_family_source: 'inferred_process',
            agent_wrapper_label: 'codex cli',
            status_source: 'transcript',
            startup_gate: 'ready',
            label: 'a new name',
            session_row_id: 42,
        });
    });
});

describe('the fields that are NOT unconditionally overwritten', () => {
    test('a pinned theme is only replaced when the live row has one', () => {
        const rows = [stale({ pinned_theme: 'amber' })];
        mergeLiveSession(rows, live({ pinned_theme: null }));
        expect(rows[0]!.pinned_theme).toBe('amber');
    });

    test('created_by_cloude comes from the server and is never derived', () => {
        const rows = [stale({ created_by_cloude: true })];
        mergeLiveSession(rows, live({ created_by_cloude: false }));
        expect(rows[0]!.created_by_cloude).toBe(false);
    });

    describe('Carnivore rename Phase 7: created_by_us wins when both are on the wire', () => {
        test('a merged existing row prefers created_by_us over created_by_cloude', () => {
            const rows = [stale({ created_by_cloude: false })];
            mergeLiveSession(rows, live({ created_by_cloude: false, created_by_us: true }));
            expect(rows[0]!.created_by_cloude).toBe(true);
        });

        test('a brand new live-only row also prefers created_by_us', () => {
            const rows: RunningSessionRow[] = [];
            mergeLiveSession(
                rows,
                live({ tmux_session: 'cloude_new', created_by_cloude: false, created_by_us: true }),
            );
            expect(rows[0]!.created_by_cloude).toBe(true);
        });

        test('an absent created_by_us still falls back to created_by_cloude, on both merge paths', () => {
            const existingRows = [stale({ created_by_cloude: false })];
            mergeLiveSession(existingRows, live({ created_by_cloude: true }));
            expect(existingRows[0]!.created_by_cloude).toBe(true);

            const newRows: RunningSessionRow[] = [];
            mergeLiveSession(newRows, live({ tmux_session: 'cloude_new', created_by_cloude: true }));
            expect(newRows[0]!.created_by_cloude).toBe(true);
        });
    });
});

describe('a live-only row and the epoch it cannot have', () => {
    test('is unshifted to the FRONT, and marked active', () => {
        const rows = [stale({ name: 'cloude_other' })];
        mergeLiveSession(rows, live({ tmux_session: 'cloude_new' }));
        expect(rows.map((r) => r.name)).toEqual(['cloude_new', 'cloude_other']);
        expect(rows[0]!.is_active).toBe(true);
    });

    test('carries a ZERO epoch, because SessionInfo has none', () => {
        const rows: RunningSessionRow[] = [];
        mergeLiveSession(rows, live({ tmux_session: 'cloude_new' }));
        expect(rows[0]!.created_at_epoch).toBe(0);
    });

    test('an existing row KEEPS its own epoch across the merge', () => {
        const rows = [stale({ created_at_epoch: 1788016091 })];
        mergeLiveSession(rows, live());
        expect(rows[0]!.created_at_epoch).toBe(1788016091);
    });
});

describe('a dead pane is not a running session', () => {
    test('a MEASURED dead row is dropped', () => {
        const rows = [stale({ name: 'cloude_dead', status: 'dead' }), stale()];
        expect(filterDeadPanes(rows).map((r) => r.name)).toEqual(['cloude_a']);
    });

    test('an UNKNOWN row is KEPT: could-not-tell is not a death', () => {
        const rows = [stale({ name: 'cloude_unknown', status: 'unknown' })];
        expect(filterDeadPanes(rows).map((r) => r.name)).toEqual(['cloude_unknown']);
    });

    test('a row with no status at all is kept for the same reason', () => {
        const rows = [stale({ name: 'cloude_quiet', status: null })];
        expect(filterDeadPanes(rows)).toHaveLength(1);
    });

    test('a listing of ONLY dead rows yields none, and does not throw', () => {
        const rows = [stale({ status: 'dead' }), stale({ name: 'b', status: 'dead' })];
        expect(filterDeadPanes(rows)).toEqual([]);
    });

    test('a live row that goes dead is dropped after the merge, not before', () => {
        const rows = [stale()];
        mergeLiveSessions(rows, [live({ activity_status: 'dead' })]);
        expect(rows).toHaveLength(1);
        expect(filterDeadPanes(rows)).toEqual([]);
    });
});

describe('the attachable body, and what a non-array means', () => {
    test('an array is the list', () => {
        const listing = emptyListing();
        expect(rowsFromAttachable([stale()], listing, 'detail')).toHaveLength(1);
        expect(listing.ok).toBe(true);
    });

    test('a non-array 200 is UNKNOWN, not empty', () => {
        const listing = emptyListing();
        expect(rowsFromAttachable({ oops: true }, listing, 'the body was not a list'))
            .toEqual([]);
        expect(listing.ok).toBe(false);
        expect(listing.reason).toBe('malformed_response');
        expect(listing.detail).toBe('the body was not a list');
        expect(listing.sources).toEqual(['attachable']);
    });

    test('an EMPTY array is a measured zero and raises no alarm', () => {
        // NEGATIVE CONTROL for
        const listing = emptyListing();
        expect(rowsFromAttachable([], listing, 'detail')).toEqual([]);
        expect(listing.ok).toBe(true);
    });
});
