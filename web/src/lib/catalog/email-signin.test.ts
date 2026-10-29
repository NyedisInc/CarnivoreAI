import { describe, expect, test } from 'vitest';

import {
    emailRefusalKey,
    isEmailUnconfigured,
    looksLikeAddress,
    looksLikeCode,
    minutesOf,
    secondsLeft,
    stepAfterRefusal,
    MAX_CODE_CHARS,
    MAX_EMAIL_CHARS,
} from './email-signin';

describe('where a refusal leaves the flow', () => {
    test('a wrong code keeps the code step, because the challenge lives', () => {
        expect(stepAfterRefusal('code_mismatch')).toBe('code');
    });

    test('a body that was not a code keeps it too', () => {
        expect(stepAfterRefusal('bad_code')).toBe('code');
    });

    test('a dead challenge sends you back to the start', () => {
        expect(stepAfterRefusal('code_expired')).toBe('address');
        expect(stepAfterRefusal('unknown_flow')).toBe('address');
    });

    test('so does every refusal that is not about the code at all', () => {
        for (const code of [
            'rate_limited',
            'email_refused',
            'bad_email',
            'account_disabled',
            'email_auth_not_configured',
            'unavailable',
            null,
            undefined,
        ]) {
            expect(stepAfterRefusal(code)).toBe('address');
        }
    });
});

describe('which failure means the feature is not built here', () => {
    test('only the email code disables the email control', () => {
        expect(isEmailUnconfigured('email_auth_not_configured')).toBe(true);
    });

    test('the GITHUB not-configured code does NOT', () => {
        expect(isEmailUnconfigured('auth_not_configured')).toBe(false);
    });

    test('and an outage does not either', () => {
        for (const code of ['unavailable', 'rate_limited', null, undefined, '']) {
            expect(isEmailUnconfigured(code)).toBe(false);
        }
    });
});

describe('the countdown', () => {
    test('it counts whole seconds down', () => {
        expect(secondsLeft(10_000, 4_500)).toBe(6);
    });

    test('it floors at zero and never reports a negative', () => {
        expect(secondsLeft(1_000, 9_000)).toBe(0);
        expect(secondsLeft(0, 60_000)).toBe(0);
    });

    test('an unreadable clock reads as expired rather than as forever', () => {
        expect(secondsLeft(Number.NaN, 1_000)).toBe(0);
        expect(secondsLeft(1_000, Number.NaN)).toBe(0);
    });

    test('minutes are whole and never zero', () => {
        expect(minutesOf(900)).toBe(15);
        expect(minutesOf(90)).toBe(1);
        expect(minutesOf(10)).toBe(1);
        expect(minutesOf(0)).toBe(1);
        expect(minutesOf(Number.NaN)).toBe(1);
    });
});

describe('what is worth sending', () => {
    test('an ordinary address is', () => {
        expect(looksLikeAddress('ada@example.test')).toBe(true);
        expect(looksLikeAddress('  Ada@Example.test  ')).toBe(true);
    });

    test('what could never be delivered to is not', () => {
        for (const value of ['', '   ', 'ada', 'a@b@c.test', '@b.test', 'a@', 'a b@c.test']) {
            expect(looksLikeAddress(value)).toBe(false);
        }
        expect(looksLikeAddress('a'.repeat(MAX_EMAIL_CHARS) + '@b.test')).toBe(false);
    });

    test('a code is digits, something, and not absurdly long', () => {
        expect(looksLikeCode('12345678')).toBe(true);
        expect(looksLikeCode(' 12345678 ')).toBe(true);
        expect(looksLikeCode('123456')).toBe(true);
    });

    test('and anything that cannot be one is refused before an attempt', () => {
        for (const value of ['', '   ', '12ab5678', '1234-5678', '+12345678']) {
            expect(looksLikeCode(value)).toBe(false);
        }
        expect(looksLikeCode('1'.repeat(MAX_CODE_CHARS + 1))).toBe(false);
    });
});

describe('the sentence a refusal gets', () => {
    test('every code this flow can see is in the shared table', () => {
        for (const code of [
            'bad_email',
            'bad_code',
            'email_refused',
            'code_mismatch',
            'code_expired',
            'account_disabled',
            'email_auth_not_configured',
            'rate_limited',
            'unknown_flow',
            'unavailable',
        ]) {
            expect(emailRefusalKey(code)).toBe(`skill.refused.${code}`);
        }
    });

    test('a code from a newer server is still reportable', () => {
        expect(emailRefusalKey('something_new')).toBe('skill.refused.unrecognised');
    });
});
