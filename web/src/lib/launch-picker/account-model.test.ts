import { describe, expect, it } from 'vitest';
import { appliesTo, viewFor } from './account-model';
import type { RestartAccounts } from './account-types';
import type { PickerRow } from './picker-model';

const both: RestartAccounts = {
    options: [
        { id: 'work', name: 'work', provider: 'claude' },
        { id: '0123456789ab-work-relay-codex', name: 'work (relayed)', provider: 'codex' },
    ],
    selected_id: 'work',
    selected_by_provider: { claude: 'work', codex: '0123456789ab-work-relay-codex' },
};

describe('launch picker accounts by provider (#2794)', () => {
    it('a codex profile that follows the active account gets the control, a shell profile does not', () => {
        expect(appliesTo({ harness: 'codex', followsActive: true } as PickerRow, both)).toBe(true);
        expect(appliesTo({ harness: 'shell', followsActive: true } as PickerRow, both)).toBe(false);
    });
    it('each profile sees only its own provider options and preselection', () => {
        const codex = viewFor({ harness: 'codex' } as PickerRow, both)!;
        expect(codex.options.map((o) => o.id)).toEqual(['0123456789ab-work-relay-codex']);
        expect(codex.selected_id).toBe('0123456789ab-work-relay-codex');
        const claude = viewFor({ harness: 'claude' } as PickerRow, both)!;
        expect(claude.options.map((o) => o.id)).toEqual(['work']);
        expect(claude.selected_id).toBe('work');
    });
    it('a restart read, one family with no per-provider map, keeps its own preselection', () => {
        const restart: RestartAccounts = { options: [{ id: 'r', name: 'r', provider: 'codex' }], selected_id: 'r', pinned: true };
        const view = viewFor({ harness: '', data: { family: 'codex' } } as unknown as PickerRow, restart)!;
        expect(view.selected_id).toBe('r');
        expect(view.options).toHaveLength(1);
    });
});
