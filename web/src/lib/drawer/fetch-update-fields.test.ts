import { describe, expect, test } from 'vitest';

import { mergeLiveRow, type DrawerRow } from './fetch';

describe('mergeLiveRow carries background_open, agent_update and notifications_muted', () => {
    test('an existing row is updated with all three', () => {
        const rows: DrawerRow[] = [{ name: 'cloude_a' }];
        mergeLiveRow(rows, {
            tmux_session: 'cloude_a',
            background_open: 3,
            agent_update: { running: '1.10.0', installed: '1.11.0', ready: true },
            notifications_muted: true,
        });
        expect(rows[0]!.background_open).toBe(3);
        expect(rows[0]!.agent_update).toEqual({ running: '1.10.0', installed: '1.11.0', ready: true });
        expect(rows[0]!.notifications_muted).toBe(true);
    });

    test('a row built from nothing (no attachable entry) carries all three', () => {
        const rows: DrawerRow[] = [];
        mergeLiveRow(rows, {
            tmux_session: 'cloude_b',
            background_open: 2,
            agent_update: { running: '1.10.0', installed: '1.11.0', ready: false },
            notifications_muted: true,
        });
        expect(rows[0]!.background_open).toBe(2);
        expect(rows[0]!.agent_update).toEqual({ running: '1.10.0', installed: '1.11.0', ready: false });
        expect(rows[0]!.notifications_muted).toBe(true);
    });

    test('overwrite-only: a stale value on the row is cleared, never kept, when the server now sends null/false', () => {
        const rows: DrawerRow[] = [{
            name: 'cloude_c',
            background_open: 5,
            agent_update: { running: '1.9.0', installed: '1.11.0', ready: true },
            notifications_muted: true,
        }];
        mergeLiveRow(rows, {
            tmux_session: 'cloude_c',
            background_open: null,
            agent_update: null,
            notifications_muted: false,
        });
        expect(rows[0]!.background_open).toBeNull();
        expect(rows[0]!.agent_update).toBeNull();
        expect(rows[0]!.notifications_muted).toBe(false);
    });

    test('a pre-#1044/#1061 server sending nothing answers null/false, not undefined', () => {
        const rows: DrawerRow[] = [{ name: 'cloude_d' }];
        mergeLiveRow(rows, { tmux_session: 'cloude_d' });
        expect(rows[0]!.background_open).toBeNull();
        expect(rows[0]!.agent_update).toBeNull();
        expect(rows[0]!.notifications_muted).toBe(false);
    });
});
