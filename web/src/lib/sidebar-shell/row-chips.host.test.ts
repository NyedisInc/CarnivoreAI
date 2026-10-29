import { describe, expect, test } from 'vitest';

import { hostChip } from './row-chips';
import type { SidebarRow } from './legacy';

function row(overrides: Partial<SidebarRow>): SidebarRow {
    return { name: 'cloude_a', ...overrides };
}

describe('hostChip', () => {
    test('a local row (the default, and the common case) draws nothing', () => {
        expect(hostChip(row({}))).toBeNull();
        expect(hostChip(row({ host_key: 'local' }))).toBeNull();
    });

    test('a reachable remote row shows its label with no state attribute', () => {
        const chip = hostChip(row({ host_key: 'hosta', host_label: 'Hosta', host_state: 'up' }));
        expect(chip?.text).toBe('Hosta');
        expect(chip?.attrs['data-host-state']).toBeUndefined();
        expect(chip?.attrs.class).toBe('session-sidebar-row-badge session-sidebar-row-host');
    });

    test('a degraded or offline remote row carries data-host-state, quietly', () => {
        const degraded = hostChip(row({ host_key: 'hosta', host_label: 'Hosta', host_state: 'degraded' }));
        expect(degraded?.attrs['data-host-state']).toBe('degraded');
        const down = hostChip(row({ host_key: 'hosta', host_label: 'Hosta', host_state: 'down' }));
        expect(down?.attrs['data-host-state']).toBe('down');
    });

    test('a missing label falls back to the key', () => {
        const chip = hostChip(row({ host_key: 'hosta', host_state: 'up' }));
        expect(chip?.text).toBe('hosta');
    });
});
