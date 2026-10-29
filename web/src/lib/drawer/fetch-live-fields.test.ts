/* list, so the */
import { describe, expect, test } from 'vitest';
import { mergeLiveRow, type DrawerRow } from './fetch';

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
});
