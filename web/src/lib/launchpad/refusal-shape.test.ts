import { describe, expect, test } from 'vitest';

import { refusalCode, refusalStatus, refusedWith } from './refusal-shape';

function apiError(message: string, status?: number, body?: Record<string, unknown>): Error {
    return Object.assign(new Error(message), { status, body });
}

describe('refusalStatus and refusalCode', () => {
    test('read the structured fields, and null for anything else', () => {
        expect(refusalStatus(apiError('x', 409))).toBe(409);
        expect(refusalStatus(new Error('HTTP 409'))).toBeNull();
        expect(refusalStatus('HTTP 409')).toBeNull();
        expect(refusalCode(apiError('x', 409, { code: 'a' }))).toBe('a');
        expect(refusalCode(apiError('x', 409, { detail: { code: 'b' } }))).toBe('b');
        expect(refusalCode(apiError('x', 409, {}))).toBeNull();
    });
});

describe('refusedWith', () => {
    test('a code match wins, whatever the sentence says', () => {
        expect(refusedWith(apiError('anything', 409, { code: 'session_already_running' }), { code: 'session_already_running' })).toBe(true);
    });

    test('a known status that differs is never a match, even when the sentence has the words', () => {
        expect(refusedWith(apiError('a session is already running', 500), { status: 409, phrase: 'already running' })).toBe(false);
    });

    test('a status match needs no words when no phrase is asked for', () => {
        expect(refusedWith(apiError('project 4091 is gone', 404), { status: 404 })).toBe(true);
        expect(refusedWith(apiError('project 400 is gone', 404), { status: 400 })).toBe(false);
    });

    test('an error with no status falls back to the phrase only', () => {
        expect(refusedWith(new Error('a session is already running'), { status: 409, phrase: 'already running' })).toBe(true);
        expect(refusedWith(new Error('HTTP 409'), { status: 409 })).toBe(false);
    });
});
