/* list, so the */
import { describe, expect, test } from 'vitest';
import { defaultSort, mergeLiveRow, type DrawerRow } from './fetch';

const info = {
    tmux_session: 'cloude_p', activity_status: 'working', unread: true, session: { id: 'ses_p', working_dir: '/w' },
    project_id: 7, project_name: 'p', running_model: 'opus', running_model_effort: 'high', running_model_tier: 'max',
    subagents_running: 2, background_open: 1, task_lead: true, host_key: 'peer',
};

describe('mergeLiveRow live fields', () => {
    test('an updated row ends up with the same live fields as a row built from nothing', () => {
        const updated: DrawerRow[] = [{ name: 'cloude_p' }];
        const built: DrawerRow[] = [];
        mergeLiveRow(updated, info);
        mergeLiveRow(built, info);
        const { name: _n1, ...u } = updated[0]!;
        const { name: _n2, ...b } = built[0]!;
        for (const key of Object.keys(b)) {
            if (['created_at_epoch', 'session_row_id', 'label', 'agent_family', 'agent_family_source', 'agent_wrapper_icon', 'pinned_theme'].includes(key)) continue;
            expect((u as Record<string, unknown>)[key], key).toEqual((b as Record<string, unknown>)[key]);
        }
    });

    test('a field the server stopped sending becomes null on update, never the previous poll value', () => {
        const rows: DrawerRow[] = [{ name: 'cloude_p', project_id: 7, project_name: 'p', running_model: 'opus', background_open: 4 }];
        mergeLiveRow(rows, { tmux_session: 'cloude_p' });
        expect(rows[0]!.project_id).toBeNull();
        expect(rows[0]!.project_name).toBeNull();
        expect(rows[0]!.running_model).toBeNull();
        expect(rows[0]!.background_open).toBeNull();
    });

    test('wires session.tmux_created_epoch onto created_at_epoch so unworked peer rows sort identically (#3385)', () => {
        const rows: DrawerRow[] = [];
        mergeLiveRow(rows, {
            tmux_session: 'peer_older',
            host_key: 'peer-1',
            session: { id: 'remote:peer-1:peer_older', working_dir: '/w', tmux_created_epoch: 1795600100 },
        });
        mergeLiveRow(rows, {
            tmux_session: 'peer_newer',
            host_key: 'peer-2',
            session: { id: 'remote:peer-2:peer_newer', working_dir: '/w', tmux_created_epoch: 1795600900 },
        });
        mergeLiveRow(rows, {
            tmux_session: 'peer_unknown',
            host_key: 'peer-3',
            session: { id: 'remote:peer-3:peer_unknown', working_dir: '/w', tmux_created_epoch: null },
        });
        expect(rows.find((r) => r.name === 'peer_older')!.created_at_epoch).toBe(1795600100);
        expect(rows.find((r) => r.name === 'peer_newer')!.created_at_epoch).toBe(1795600900);
        expect(rows.find((r) => r.name === 'peer_unknown')!.created_at_epoch).toBe(0);
        defaultSort(rows);
        expect(rows.map((r) => r.name)).toEqual(['peer_newer', 'peer_older', 'peer_unknown']);

        const existing: DrawerRow[] = [
            { name: 'local_kept', created_at_epoch: 1795600500 },
            { name: 'local_filled', created_at_epoch: 0 },
        ];
        mergeLiveRow(existing, { tmux_session: 'local_kept', session: { id: 'ses_1', working_dir: '/w' } });
        mergeLiveRow(existing, { tmux_session: 'local_filled', session: { id: 'ses_2', working_dir: '/w', tmux_created_epoch: 1795600700 } });
        expect(existing[0]!.created_at_epoch).toBe(1795600500);
        expect(existing[1]!.created_at_epoch).toBe(1795600700);
    });
});
