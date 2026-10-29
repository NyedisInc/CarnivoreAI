import { describe, expect, test } from 'vitest';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import {
    describeRow,
    recentView,
    restartPlan,
    stateOf,
    type RecentSessionRecord,
    type Translate,
} from './recent';

const i18n = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => i18n.t(key, params);

const derive = (name: string): string => name.replace(/^cloude_/, '');

function rowAt<T>(rows: readonly T[], n: number): T {
    const found = rows[n];
    expect(found, `no row at index ${n}`).toBeDefined();
    return found as T;
}

function row(overrides: Partial<RecentSessionRecord> = {}): RecentSessionRecord {
    return {
        id: 1,
        session_uuid: 'uuid-1',
        tmux_name: 'cloude_stopped_one',
        lifecycle: 'stopped',
        working_dir: '/tmp/proj',
        agent_type: 'claude',
        archived_at: null,
        title: null,
        ...overrides,
    };
}

describe('the three-outcome contract on the whole group', () => {
    test("`ok` with a stopped row renders that row and offers a restart", () => {
        const view = recentView({ state: 'ok', sessions: [row()] }, [], false, derive, t);
        expect(view.kind).toBe('rows');
        if (view.kind !== 'rows') return;
        expect(view.rows).toHaveLength(1);
        expect(rowAt(view.rows, 0).canRestart).toBe(true);
        expect(rowAt(view.rows, 0).restart).not.toBeNull();
    });

    test.each(['probe_unavailable', 'never_probed'])(
        "`%s` renders the notice and CANNOT render rows, even with sessions present",
        (state) => {
            const view = recentView(
                { state, sessions: [row(), row({ session_uuid: 'uuid-2' })], notice: null },
                [], false, derive, t,
            );
            expect(view.kind).toBe('unavailable');
            if (view.kind !== 'unavailable') return;
            expect(view.state).toBe(state);
            expect(view.title.length).toBeGreaterThan(0);
            expect(view.detail.length).toBeGreaterThan(0);
            expect('rows' in view).toBe(false);
        },
    );

    test('the server notice is preferred over the fallback detail', () => {
        const view = recentView(
            { state: 'probe_unavailable', sessions: [], notice: 'the last tmux probe timed out' },
            [], false, derive, t,
        );
        expect(view.kind).toBe('unavailable');
        if (view.kind !== 'unavailable') return;
        // its own sentence
        expect(view.detail).toBe('the last tmux probe timed out');
    });

    test('a body with no state at all is NOT read as healthy', () => {
        expect(stateOf(null)).toBe('never_probed');
        expect(stateOf({})).toBe('never_probed');
        expect(stateOf({ state: '  ' })).toBe('never_probed');
        expect(recentView(null, [], false, derive, t).kind).toBe('unavailable');
    });

    test('`ok` with zero rows hides the section, with no attention block', () => {
        expect(recentView({ state: 'ok', sessions: [] }, [], false, derive, t).kind)
            .toBe('hidden');
    });

    test('`ok` with zero rows KEEPS the section up while the archive filter is on', () => {
        const view = recentView({ state: 'ok', sessions: [] }, [], true, derive, t);
        expect(view.kind).toBe('empty');
        if (view.kind !== 'empty') return;
        expect(view.message.length).toBeGreaterThan(0);
    });

    test('the count says how many rows are ON SCREEN, not how many arrived', () => {
        const rows = [row({ id: 1 }), row({ id: 2, session_uuid: 'uuid-2' })];
        const view = recentView(
            { state: 'ok', sessions: rows },
            [{ name: 'cloude_stopped_one', session_row_id: 2 }],
            false, derive, t,
        );
        expect(view.kind).toBe('rows');
        if (view.kind !== 'rows') return;
        expect(view.rows).toHaveLength(1);
        expect(view.count).toContain('1');
    });
});

describe('the restart gate is enforced at the render layer, not only by the query', () => {
    test.each(['unknown', 'running', 'archived', ''])(
        "a `%s` lifecycle row offers NO restart control",
        (lifecycle) => {
            const view = recentView(
                { state: 'ok', sessions: [row({ lifecycle })] }, [], false, derive, t,
            );
            expect(view.kind).toBe('rows');
            if (view.kind !== 'rows') return;
            expect(rowAt(view.rows, 0).canRestart).toBe(false);
            expect(rowAt(view.rows, 0).restart).toBeNull();
        },
    );

    test('a stopped row carries its working dir and agent type into the restart', () => {
        const view = recentView(
            {
                state: 'ok',
                sessions: [row({ working_dir: '/home/x/proj', agent_type: 'codex' })],
            },
            [], false, derive, t,
        );
        expect(view.kind).toBe('rows');
        if (view.kind !== 'rows') return;
        expect(rowAt(view.rows, 0).restart).toEqual({
            sessionUuid: 'uuid-1',
            title: '',
            workingDir: '/home/x/proj',
            agentType: 'codex',
        });
    });

    test('every stopped row gets its own restart, not one for the group', () => {
        const view = recentView(
            {
                state: 'ok',
                sessions: [
                    row({ id: 1, session_uuid: 'a', tmux_name: 'cloude_a' }),
                    row({ id: 2, session_uuid: 'b', tmux_name: 'cloude_b' }),
                ],
            },
            [], false, derive, t,
        );
        expect(view.kind).toBe('rows');
        if (view.kind !== 'rows') return;
        expect(view.rows.map((r) => r.restart?.sessionUuid)).toEqual(['a', 'b']);
    });
});

describe('a row names itself the way the user named it', () => {
    test('the title leads, because it is what the user called the session', () => {
        const r = describeRow(row({ title: '  Media Compression  ' }), derive, t);
        expect(r.name).toBe('Media Compression');
    });

    test('with no title the derived tmux name answers, then the directory', () => {
        expect(describeRow(row({ title: null }), derive, t).name).toBe('stopped_one');
        expect(describeRow(
            row({ title: null, tmux_name: null, working_dir: '/tmp/p' }), derive, t,
        ).name).toBe('/tmp/p');
    });

    test('with nothing at all it still has a name, never an empty label', () => {
        const r = describeRow(
            { session_uuid: 'u', lifecycle: 'stopped' }, derive, t,
        );
        expect(r.name.length).toBeGreaterThan(0);
    });

    test('an archived row is MARKED and keeps its restart', () => {
        const r = describeRow(row({ archived_at: '2026-09-07T13:40:24Z' }), derive, t);
        expect(r.archived).toBe(true);
        expect(r.canRestart).toBe(true);
        expect(r.restart).not.toBeNull();
    });

    test('a row with no archived_at is not marked archived', () => {
        expect(describeRow(row({ archived_at: null }), derive, t).archived).toBe(false);
    });

    test('a lifecycle we cannot act on is echoed verbatim, not translated away', () => {
        expect(describeRow(row({ lifecycle: 'wedged' }), derive, t).lifecycleLabel)
            .toBe('wedged');
    });
});

describe('when a row closed', () => {
    const now = Date.parse('2026-09-30T12:00:00Z');

    test('a recorded close reads "closed 2h ago" with the exact time on hover', () => {
        const r = describeRow(
            row({ closed_at: '2026-09-30T10:00:00Z', closed_basis: 'closed' }), derive, t, now);
        expect(r.lifecycleLabel).toBe('closed 2h ago');
        expect(r.lifecycleTitle).toContain(new Date('2026-09-30T10:00:00Z').toLocaleString());
        expect(r.lifecycleTitle.startsWith('closed ')).toBe(true);
    });

    test('a proxy stamp is labelled last active, never closed', () => {
        const r = describeRow(
            row({ closed_at: '2026-09-27T12:00:00Z', closed_basis: 'last_active' }), derive, t, now);
        expect(r.lifecycleLabel).toBe('last active 3d ago');
        expect(r.lifecycleTitle).toContain('no close was recorded');
    });

    test('an unreadable or absent stamp keeps the plain ended word', () => {
        expect(describeRow(row({ closed_at: null }), derive, t, now).lifecycleLabel).toBe('ended');
        expect(describeRow(row({ closed_at: 'garbage' }), derive, t, now).lifecycleLabel).toBe('ended');
    });
});

describe('the restart plan, which decides HOW before anything is sent', () => {
    test('a known uuid is the whole payload: the server owns the rest', () => {
        const plan = restartPlan({
            sessionUuid: 'u1', title: 'Media', workingDir: '/p', agentType: 'claude',
        });
        expect(plan.mode).toBe('restart');
        expect(plan.sessionUuid).toBe('u1');
        expect(plan.payload).toBeNull();
        expect(plan.mustExplain).toBe(false);
    });

    test('no uuid still creates a session, and MUST be explained', () => {
        const plan = restartPlan({ title: 'Media', workingDir: '/p', agentType: 'claude' });
        expect(plan.mode).toBe('create_unidentified');
        expect(plan.mustExplain).toBe(true);
        expect(plan.payload).toEqual({
            working_dir: '/p', agent_type: 'claude', project_name: 'Media',
        });
    });

    test('empty and whitespace fields are dropped, never sent as blanks', () => {
        const plan = restartPlan({ sessionUuid: '   ', title: '', workingDir: '  ' });
        expect(plan.mode).toBe('create_unidentified');
        expect(plan.payload).toEqual({});
    });

    test('a null or absent options object does not throw', () => {
        expect(restartPlan(null).mode).toBe('create_unidentified');
        expect(restartPlan(undefined).mustExplain).toBe(true);
    });
});
