import { describe, expect, test } from 'vitest';
import { isLedgerHash, ledgerAccountHash, ledgerHashTarget } from './screen-host';

describe('ledgerHashTarget', () => {
    test('the bare fragment names the screen, with or without its #', () => {
        expect(ledgerHashTarget('#ledger')).toBe('');
        expect(ledgerHashTarget('ledger')).toBe('');
    });

    test('#ledger/<id> names one account, decoded', () => {
        expect(ledgerHashTarget('#ledger/work')).toBe('work');
        expect(ledgerHashTarget('#ledger/a%20b')).toBe('a b');
    });

    test('anything else is not the ledger', () => {
        for (const hash of ['', '#', '#ledgers', '#ledger-foo', '#ledger/', '#catalog', '#ledger/%E0%A4%A', null, undefined]) {
            expect(ledgerHashTarget(hash)).toBe(null);
            expect(isLedgerHash(hash)).toBe(false);
        }
    });

    test('ledgerAccountHash round-trips through the reader', () => {
        for (const id of ['work', 'claude-1', 'a b/c#d']) {
            expect(ledgerHashTarget(ledgerAccountHash(id))).toBe(id);
        }
    });
});
