import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import {
    LEDGER_KEYS,
    removeConfirmKey,
    credentialLabel,
    credentialTone,
    formatAge,
    formatPercent,
    formatResetIn,
    formatWindowLabel,
    sortAccounts,
    type LedgerAccount,
} from './ledger-model';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

/** A fixed instant, so nothing here depends on when it is run. */
const NOW = Date.parse('2026-09-17T12:00:00Z');

function account(over: Partial<LedgerAccount>): LedgerAccount {
    return {
        id: 'a',
        name: 'one',
        provider: 'claude',
        plan: null,
        identity: null,
        credential_state: 'ok',
        fetched_at: null,
        next_poll_at: null,
        error: null,
        windows: [],
        ...over,
    };
}

describe('how long until a window resets', () => {
    test('hours and minutes read as one phrase', () => {
        const at = new Date(NOW + (2 * 3600 + 14 * 60) * 1000).toISOString();
        expect(formatResetIn(at, NOW, t)).toBe('in 2h 14m');
    });

    test('a whole number of hours drops the minutes', () => {
        const at = new Date(NOW + 3 * 3600 * 1000).toISOString();
        expect(formatResetIn(at, NOW, t)).toBe('in 3h');
    });

    test('under an hour is minutes alone', () => {
        const at = new Date(NOW + 14 * 60 * 1000).toISOString();
        expect(formatResetIn(at, NOW, t)).toBe('in 14m');
    });

    test('under a minute is seconds, never a rounded-down zero', () => {
        const at = new Date(NOW + 30 * 1000).toISOString();
        expect(formatResetIn(at, NOW, t)).toBe('in 30s');
    });

    test('a seven day window reads in days and hours', () => {
        const at = new Date(NOW + (2 * 86400 + 5 * 3600) * 1000).toISOString();
        expect(formatResetIn(at, NOW, t)).toBe('in 2d 5h');
    });

    test('a whole number of days drops the hours', () => {
        const at = new Date(NOW + 6 * 86400 * 1000).toISOString();
        expect(formatResetIn(at, NOW, t)).toBe('in 6d');
    });

    test('an instant already passed says the window reset', () => {
        const at = new Date(NOW - 1000).toISOString();
        expect(formatResetIn(at, NOW, t)).toBe(t(LEDGER_KEYS.resetPassed));
    });

    test('exactly now says the window reset, not "in 0s"', () => {
        expect(formatResetIn(new Date(NOW).toISOString(), NOW, t))
            .toBe(t(LEDGER_KEYS.resetPassed));
    });

    test('NULL IS UNKNOWN, and unknown is never "reset"', () => {
        expect(formatResetIn(null, NOW, t)).toBe(t(LEDGER_KEYS.valueUnknown));
        expect(formatResetIn(undefined, NOW, t)).toBe(t(LEDGER_KEYS.valueUnknown));
        expect(formatResetIn(null, NOW, t)).not.toBe(t(LEDGER_KEYS.resetPassed));
    });

    test('an unparseable instant is unknown rather than a NaN phrase', () => {
        expect(formatResetIn('not a date', NOW, t)).toBe(t(LEDGER_KEYS.valueUnknown));
        expect(formatResetIn('', NOW, t)).toBe(t(LEDGER_KEYS.valueUnknown));
    });
});

describe('how old a fetch or a loop pass is', () => {
    test('seconds, minutes, hours and days each have their own phrase', () => {
        const ago = (s: number) => new Date(NOW - s * 1000).toISOString();
        expect(formatAge(ago(12), NOW, t)).toBe('12s ago');
        expect(formatAge(ago(90), NOW, t)).toBe('1m ago');
        expect(formatAge(ago(7200), NOW, t)).toBe('2h ago');
        expect(formatAge(ago(3 * 86400), NOW, t)).toBe('3d ago');
    });

    test('a fetch that has never happened says so rather than "0s ago"', () => {
        expect(formatAge(null, NOW, t)).toBe(t(LEDGER_KEYS.ageNever));
    });

    test('a clock that reads ahead of the stamp floors at zero', () => {
        const ahead = new Date(NOW + 5000).toISOString();
        expect(formatAge(ahead, NOW, t)).toBe('0s ago');
    });
});

describe('the window name', () => {
    test('the label the server sent is the one that is shown', () => {
        expect(formatWindowLabel({ kind: 'seven_day_opus', label: '7d opus' }, t))
            .toBe('7d opus');
    });

    test('a missing label falls back to the kind, never to a blank cell', () => {
        expect(formatWindowLabel({ kind: 'five_hour', label: null }, t)).toBe('five_hour');
        expect(formatWindowLabel({ kind: 'primary', label: '  ' }, t)).toBe('primary');
    });

    test('a window with neither is unknown', () => {
        expect(formatWindowLabel({ kind: '', label: null }, t)).toBe(t(LEDGER_KEYS.valueUnknown));
        expect(formatWindowLabel(null, t)).toBe(t(LEDGER_KEYS.valueUnknown));
    });
});

describe('a percent', () => {
    test('ZERO IS A NUMBER AND IT PRINTS', () => {
        expect(formatPercent(0, t)).toBe('0%');
    });

    test('a hundred prints', () => {
        expect(formatPercent(100, t)).toBe('100%');
    });

    test('fractions are rounded for the eye', () => {
        expect(formatPercent(42.4, t)).toBe('42%');
    });

    test('null is unknown', () => {
        expect(formatPercent(null, t)).toBe(t(LEDGER_KEYS.valueUnknown));
    });
});

describe('the credential state', () => {
    test('every state the contract names has its own sentence', () => {
        const states = ['ok', 'expired', 'missing', 'refused', 'rate_limited', 'error', 'unknown'];
        const seen = states.map((state) => credentialLabel(state, t));
        for (const label of seen) expect(label).not.toContain('ledger.');
        expect(new Set(seen).size).toBe(states.length);
    });

    test('a state this build has never heard of still names itself', () => {
        expect(credentialLabel('teapot', t)).toContain('teapot');
    });

    test('absent is unknown, and unknown takes no status colour', () => {
        expect(credentialLabel(null, t)).toBe(t(LEDGER_KEYS.credentialUnknown));
        expect(credentialTone('unknown')).toBe('unknown');
        expect(credentialTone(null)).toBe('unknown');
    });

    test('a healthy credential is ok, a throttled one warns, a broken one is high', () => {
        expect(credentialTone('ok')).toBe('ok');
        expect(credentialTone('rate_limited')).toBe('warn');
        expect(credentialTone('expired')).toBe('warn');
        expect(credentialTone('missing')).toBe('high');
        expect(credentialTone('refused')).toBe('high');
        expect(credentialTone('error')).toBe('high');
    });
});

describe('the order the rows come out in', () => {
    test('provider first, then name', () => {
        const rows = [
            account({ id: '1', provider: 'codex', name: 'work' }),
            account({ id: '2', provider: 'claude', name: 'spare' }),
            account({ id: '3', provider: 'claude', name: 'main' }),
        ];
        expect(sortAccounts(rows).map((row) => row.id)).toEqual(['3', '2', '1']);
    });

    test('IT IS STABLE: equal keys keep the order the server sent', () => {
        const rows = [
            account({ id: 'first', provider: 'claude', name: 'same' }),
            account({ id: 'second', provider: 'claude', name: 'same' }),
            account({ id: 'third', provider: 'claude', name: 'same' }),
        ];
        expect(sortAccounts(rows).map((row) => row.id)).toEqual(['first', 'second', 'third']);
    });

    test('a nameless account sorts before a named one and is not dropped', () => {
        const rows = [
            account({ id: '1', provider: 'claude', name: 'a' }),
            account({ id: '2', provider: 'claude', name: null }),
        ];
        expect(sortAccounts(rows).map((row) => row.id)).toEqual(['2', '1']);
    });

    test('the input array is not reordered under the caller', () => {
        const rows = [
            account({ id: '1', provider: 'codex' }),
            account({ id: '2', provider: 'claude' }),
        ];
        sortAccounts(rows);
        expect(rows.map((row) => row.id)).toEqual(['1', '2']);
    });

    test('nothing in, nothing out', () => {
        expect(sortAccounts([])).toEqual([]);
    });
});

describe('the keys this surface names', () => {
    test('every one of them is in the message catalog', () => {
        const messages = enCatalog as Record<string, unknown>;
        const missing = Object.values(LEDGER_KEYS).filter((key) => !(key in messages));
        expect(missing).toEqual([]);
    });

    test('NEGATIVE CONTROL: the check can fail', () => {
        const messages = enCatalog as Record<string, unknown>;
        expect(Object.keys(messages).length).toBeGreaterThan(100);
        expect('ledger.no.such.key' in messages).toBe(false);
    });
});

describe('which question the remove confirm asks', () => {
    test('A MANAGED ROW IS TOLD ITS LOGIN AREA IS GOING', () => {
        expect(removeConfirmKey({ managed: true })).toBe(
            LEDGER_KEYS.editorRemoveConfirmManaged,
        );
    });

    test('an unmanaged row keeps the copy it has always had', () => {
        expect(removeConfirmKey({ managed: false })).toBe(
            LEDGER_KEYS.editorRemoveConfirm,
        );
    });

    test('a row that never said, which is every row written before the flag, keeps it too', () => {
        expect(removeConfirmKey({})).toBe(LEDGER_KEYS.editorRemoveConfirm);
    });

    test('the managed question names the account and the login area', () => {
        const asked = t(LEDGER_KEYS.editorRemoveConfirmManaged, { name: 'day job' });
        expect(asked).toContain('day job');
        expect(asked).toContain('login area');
    });
});
