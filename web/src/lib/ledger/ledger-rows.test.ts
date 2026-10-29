import { describe, expect, test } from 'vitest';

import { mergeConfiguredRows, UNMEASURED_CREDENTIAL_STATE } from './ledger-rows';
import type { StoredAccount } from './accounts-model';
import type { LedgerAccount } from './ledger-model';

const CONFIGURED: StoredAccount = {
    id: 'work-max',
    name: 'Work Max',
    provider: 'claude',
    claude_config_dir: '~/.claude-work',
    codex_home: '~/.codex',
};

const MEASURED: LedgerAccount = {
    id: 'work-max',
    name: 'Work Max',
    provider: 'claude',
    plan: 'max 20x',
    identity: 'acme',
    credential_state: 'ok',
    fetched_at: '2026-09-17T12:00:00Z',
    next_poll_at: '2026-09-17T12:03:00Z',
    error: null,
    windows: [{ kind: 'five_hour', label: '5h', used_pct: 12 }],
};

describe('an account that is configured but not measured yet', () => {
    test('paints one row rather than nothing', () => {
        const rows = mergeConfiguredRows([CONFIGURED], []);
        expect(rows).toHaveLength(1);
        expect(rows[0]?.id).toBe('work-max');
        expect(rows[0]?.name).toBe('Work Max');
        expect(rows[0]?.provider).toBe('claude');
    });

    test('claims no reading it has not taken', () => {
        const row = mergeConfiguredRows([CONFIGURED], [])[0];
        expect(row?.credential_state).toBe(UNMEASURED_CREDENTIAL_STATE);
        expect(row?.plan).toBeNull();
        expect(row?.identity).toBeNull();
        expect(row?.fetched_at).toBeNull();
        expect(row?.error).toBeNull();
        expect(row?.windows).toEqual([]);
    });

    test('is replaced whole by the reading once one arrives', () => {
        const rows = mergeConfiguredRows([CONFIGURED], [MEASURED]);
        expect(rows).toHaveLength(1);
        expect(rows[0]).toEqual({ ...MEASURED, color: null, managed: false });
    });
});

describe('the two lists disagreeing', () => {
    test('a measured row the configured list does not mention still paints', () => {
        const rows = mergeConfiguredRows([], [MEASURED]);
        expect(rows).toEqual([MEASURED]);
    });

    test('a configured list that could not be read invents nothing', () => {
        expect(mergeConfiguredRows(null, [MEASURED])).toEqual([MEASURED]);
        expect(mergeConfiguredRows(null, [])).toEqual([]);
    });

    test('nothing configured and nothing measured is still nothing', () => {
        expect(mergeConfiguredRows([], [])).toEqual([]);
    });

    test('an account is painted once, never twice', () => {
        const other: StoredAccount = { id: 'personal', name: 'Personal', provider: 'codex' };
        const rows = mergeConfiguredRows([CONFIGURED, other], [MEASURED]);
        expect(rows.map((row) => row.id)).toEqual(['work-max', 'personal']);
    });
});

describe('what it does to the arrays it was handed', () => {
    test('neither one is reordered underneath the caller', () => {
        const configured = [CONFIGURED];
        const measured = [MEASURED];
        mergeConfiguredRows(configured, measured);
        expect(configured).toEqual([CONFIGURED]);
        expect(measured).toEqual([MEASURED]);
    });
});

describe('the colour and the managed flag, which are CONFIGURED facts', () => {
    test('a placeholder row carries the colour that was just written', () => {
        const rows = mergeConfiguredRows([{ ...CONFIGURED, color: '#a3e635' }], []);
        expect(rows[0]?.color).toBe('#a3e635');
    });

    test('a placeholder row with no colour carries null, never a default one', () => {
        const rows = mergeConfiguredRows([CONFIGURED], []);
        expect(rows[0]?.color).toBeNull();
    });

    test('a placeholder row carries whether the app owns its directory', () => {
        const rows = mergeConfiguredRows([{ ...CONFIGURED, managed: true }], []);
        expect(rows[0]?.managed).toBe(true);
    });

    test('a row written before the flag existed reads as not managed', () => {
        const rows = mergeConfiguredRows([CONFIGURED], []);
        expect(rows[0]?.managed).toBe(false);
    });

    test('THE CONFIGURED COLOUR WINS OVER THE MEASURED ONE', () => {
        const rows = mergeConfiguredRows(
            [{ ...CONFIGURED, color: '#818cf8' }],
            [{ ...MEASURED, color: '#a3e635' }],
        );
        expect(rows[0]?.color).toBe('#818cf8');
    });

    test('taking a colour off wins too, rather than the old one lingering', () => {
        const rows = mergeConfiguredRows([CONFIGURED], [{ ...MEASURED, color: '#a3e635' }]);
        expect(rows[0]?.color).toBeNull();
    });

    test('EVERY MEASURED FIELD IS UNTOUCHED BY THE OVERLAY', () => {
        const rows = mergeConfiguredRows([{ ...CONFIGURED, color: '#818cf8' }], [MEASURED]);
        expect(rows[0]?.plan).toBe('max 20x');
        expect(rows[0]?.identity).toBe('acme');
        expect(rows[0]?.credential_state).toBe('ok');
        expect(rows[0]?.windows).toEqual(MEASURED.windows);
    });

    test('a measured row nobody configured keeps its own colour', () => {
        const rows = mergeConfiguredRows([], [{ ...MEASURED, color: '#a3e635' }]);
        expect(rows[0]?.color).toBe('#a3e635');
    });

    test('an unreadable configured list leaves every measured row alone', () => {
        const rows = mergeConfiguredRows(null, [{ ...MEASURED, color: '#a3e635' }]);
        expect(rows[0]?.color).toBe('#a3e635');
    });
});
