import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import {
    formatLoginCountdown,
    loginExpiryTone,
    pokeFailure,
    type LedgerAccount,
} from './ledger-model';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const NOW = Date.parse('2026-09-18T12:00:00Z');

const DAY = 86400 * 1000;

function inDays(days: number): string {
    return new Date(NOW + days * DAY).toISOString();
}

describe('the catalog carries every key this surface prints', () => {
    test('the login countdown and refresh strings exist', () => {
        expect(enCatalog['ledger.login_countdown.days']).toBeTruthy();
        expect(enCatalog['ledger.login_countdown.hours']).toBeTruthy();
        expect(enCatalog['ledger.login_countdown.expired']).toBeTruthy();
        expect(enCatalog['ledger.poke.failed']).toBeTruthy();
    });
});

describe('loginExpiryTone', () => {
    test('nothing to paint while the login is healthy', () => {
        expect(loginExpiryTone(inDays(29), NOW)).toBeNull();
        expect(loginExpiryTone(null, NOW)).toBeNull();
    });

    test('a fortnight out is a warning', () => {
        expect(loginExpiryTone(inDays(13), NOW)).toBe('warn');
        expect(loginExpiryTone(inDays(3), NOW)).toBe('warn');
    });

    test('the fortnight boundary itself is still quiet', () => {
        expect(loginExpiryTone(inDays(14), NOW)).toBeNull();
    });

    test('under three days is the danger colour', () => {
        expect(loginExpiryTone(inDays(2), NOW)).toBe('high');
    });

    test('and so is a deadline that has passed', () => {
        expect(loginExpiryTone(inDays(-1), NOW)).toBe('high');
    });
});

describe('pokeFailure', () => {
    const account = (poke: LedgerAccount['poke']): LedgerAccount => ({
        id: 'max-main',
        provider: 'claude',
        poke,
    });

    test('says nothing when no poke has ever been attempted', () => {
        expect(pokeFailure(account(null), t)).toBeNull();
        expect(pokeFailure(account(undefined), t)).toBeNull();
    });

    test('says nothing about a poke that worked', () => {
        expect(pokeFailure(account({ state: 'idle', error: null }), t)).toBeNull();
    });

    test('names the reason a refresh did not happen', () => {
        expect(pokeFailure(account({ state: 'failed', error: 'poke_no_refresh' }), t)).toBe(
            'automatic refresh failed: poke_no_refresh',
        );
    });

    test('a failure with no reason prints no sentence', () => {
        expect(pokeFailure(account({ state: 'failed', error: null }), t)).toBeNull();
    });

    test('a poke stopped at its bound says unknown, never failed (issue #517)', () => {
        expect(pokeFailure(account({ state: 'unknown', error: 'poke_timed_out' }), t)).toBe(
            'automatic refresh outcome unknown: poke_timed_out',
        );
    });

    test('a revoked login says to sign in again', () => {
        expect(pokeFailure(account({ state: 'needs_login', error: 'needs_login' }), t)).toBe(
            'login revoked, sign in again',
        );
    });
});

describe('formatLoginCountdown: the ledger card line always speaks when a deadline exists', () => {
    test('whole days, even a month out, in the quiet tone', () => {
        expect(formatLoginCountdown(inDays(29.5), NOW, t)).toBe('login expires in 29d');
        expect(loginExpiryTone(inDays(29.5), NOW)).toBeNull();
        expect(formatLoginCountdown(inDays(12), NOW, t)).toBe('login expires in 12d');
    });

    test('hours under a day, never zero', () => {
        expect(formatLoginCountdown(inDays(0.5), NOW, t)).toBe('login expires in 12h');
        expect(formatLoginCountdown(new Date(NOW + 60_000).toISOString(), NOW, t)).toBe(
            'login expires in 1h',
        );
    });

    test('past the deadline it says expired', () => {
        expect(formatLoginCountdown(inDays(-1), NOW, t)).toBe('login expired');
    });

    test('absent or unreadable is no line at all, never a date', () => {
        expect(formatLoginCountdown(null, NOW, t)).toBeNull();
        expect(formatLoginCountdown(undefined, NOW, t)).toBeNull();
        expect(formatLoginCountdown('not a date', NOW, t)).toBeNull();
    });
});
