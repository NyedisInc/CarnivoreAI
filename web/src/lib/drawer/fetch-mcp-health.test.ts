import { describe, expect, test } from 'vitest';

import { mergeLiveRow, type DrawerRow } from './fetch';

const DROP = { dropped: [{ name: 'carnivore', state: 'dropped', exact: true }] };

describe('mergeLiveRow carries mcp_health', () => {
    test('an existing row and a built row both take it', () => {
        const rows: DrawerRow[] = [{ name: 'cloude_a' }];
        mergeLiveRow(rows, { tmux_session: 'cloude_a', mcp_health: DROP });
        expect(rows[0]!.mcp_health).toEqual(DROP);
        const built: DrawerRow[] = [];
        mergeLiveRow(built, { tmux_session: 'cloude_b', mcp_health: DROP });
        expect(built[0]!.mcp_health).toEqual(DROP);
    });

    test('overwrite-only: null replaces a stale drop and an absent field answers null', () => {
        const rows: DrawerRow[] = [{ name: 'cloude_c', mcp_health: DROP }];
        mergeLiveRow(rows, { tmux_session: 'cloude_c', mcp_health: null });
        expect(rows[0]!.mcp_health).toBeNull();
        const bare: DrawerRow[] = [{ name: 'cloude_d' }];
        mergeLiveRow(bare, { tmux_session: 'cloude_d' });
        expect(bare[0]!.mcp_health).toBeNull();
    });
});
