import { describe, expect, test } from 'vitest';

import { mergeLiveRow, type DrawerRow } from './fetch';

describe('the merged row carries its host', () => {
    test('a remote row updates an existing attachable row with its host', () => {
        const rows: DrawerRow[] = [{ name: 'cloude_a' }];
        mergeLiveRow(rows, {
            tmux_session: 'cloude_a',
            host_key: 'studio',
            host_label: 'Studio',
            host_state: 'up',
        });
        expect(rows[0]!.host_key).toBe('studio');
        expect(rows[0]!.host_label).toBe('Studio');
        expect(rows[0]!.host_state).toBe('up');
    });

    test('a remote row with no existing entry still carries its host', () => {
        const rows: DrawerRow[] = [];
        mergeLiveRow(rows, {
            tmux_session: 'cloude_b',
            host_key: 'studio',
            host_label: 'Studio',
            host_state: 'degraded',
        });
        expect(rows[0]!.host_key).toBe('studio');
        expect(rows[0]!.host_state).toBe('degraded');
    });

    test('no host fields at all (a pre-#162 server) defaults to local', () => {
        const existingRows: DrawerRow[] = [{ name: 'cloude_c' }];
        mergeLiveRow(existingRows, { tmux_session: 'cloude_c' });
        expect(existingRows[0]!.host_key).toBe('local');
        expect(existingRows[0]!.host_label).toBe('this machine');
        expect(existingRows[0]!.host_state).toBe('up');

        const newRows: DrawerRow[] = [];
        mergeLiveRow(newRows, { tmux_session: 'cloude_d' });
        expect(newRows[0]!.host_key).toBe('local');
        expect(newRows[0]!.host_label).toBe('this machine');
        expect(newRows[0]!.host_state).toBe('up');
    });
});
