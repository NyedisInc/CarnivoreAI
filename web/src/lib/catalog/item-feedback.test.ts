import { describe, expect, test, vi } from 'vitest';

// EVERYTHING THE MOCK FACTORY TOUCHES MUST BE `vi.hoisted`, INCLUDING THE
const { authFetchCalls, authFetchAnswers, FakeApiError } = vi.hoisted(() => {
    class FakeApiError extends Error {
        readonly status: number;
        readonly code: string | null;
        readonly payload: unknown;
        constructor(message: string, status: number, code: string | null, payload: unknown) {
            super(message);
            this.name = 'ApiError';
            this.status = status;
            this.code = code;
            this.payload = payload;
        }
    }
    return {
        authFetchCalls: [] as Array<{ path: string; method: string; body: unknown }>,
        authFetchAnswers: [] as unknown[],
        FakeApiError,
    };
});

vi.mock('../../opscenter/api/auth.svelte', () => ({
    ApiError: FakeApiError,
    authFetch: (path: string, init: RequestInit = {}) => {
        authFetchCalls.push({
            path,
            method: (init.method ?? 'GET').toUpperCase(),
            body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
        });
        const answer = authFetchAnswers.shift();
        if (answer instanceof Error) return Promise.reject(answer);
        return Promise.resolve(answer ?? {});
    },
}));

import { developerOf, reasonOfNoteFailure, sendNote } from './item-feedback';
import { i18n } from '../i18n/index.svelte';

const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

describe('developerOf', () => {
    test('a handle opens the in-app profile and carries no github link by itself', () => {
        expect(developerOf({ publisher: 'example-owner', author: null })).toEqual({
            kind: 'publisher', handle: 'example-owner', profileHandle: 'example-owner', githubHref: null,
        });
    });

    test('a server-stamped github login gives exactly https://github.com/<login>', () => {
        const dev = developerOf({ publisher: 'example-owner', publisherGithub: 'example-owner', author: null });
        expect(dev).toMatchObject({ githubHref: 'https://github.com/example-owner' });
    });

    test('a hostile handle or login never becomes a url or a profile', () => {
        for (const bad of ['evil.com/x', '../', 'Not A Handle', 'a/b', 'x?y=1']) {
            const dev = developerOf({ publisher: bad, publisherGithub: bad, author: null });
            expect(dev).toEqual({ kind: 'publisher', handle: bad, profileHandle: null, githubHref: null });
        }
    });

    test('a publisher present but the author also set - publisher wins', () => {
        const dev = developerOf({ publisher: 'example-owner', author: 'NYX-9' });
        expect(dev.kind).toBe('publisher');
    });

    test('no publisher falls back to the manifest author', () => {
        const dev = developerOf({ publisher: null, author: 'NYX-9' });
        expect(dev).toEqual({ kind: 'author', text: 'NYX-9' });
    });

    test('a blank author is treated the same as none', () => {
        expect(developerOf({ publisher: null, author: '   ' })).toEqual({ kind: 'unset' });
    });

    test('neither is unset', () => {
        expect(developerOf({ publisher: null, author: null })).toEqual({ kind: 'unset' });
    });
});

describe('sendNote', () => {
    test('posts the exact text to the encoded item path and unwraps the answer', async () => {
        authFetchAnswers.push({ item_id: 'bundled/matrix', created_at: '2026-09-22T00:00:00Z' });
        const answer = await sendNote('bundled/matrix', 'the reds clash on ansi 3');
        expect(authFetchCalls).toEqual([
            {
                path: '/catalog/items/bundled%2Fmatrix/note',
                method: 'POST',
                body: { text: 'the reds clash on ansi 3' },
            },
        ]);
        expect(answer).toEqual({ itemId: 'bundled/matrix', createdAt: '2026-09-22T00:00:00Z' });
    });

    test('an absent field on the answer comes back null, never undefined or a default', async () => {
        authFetchAnswers.push({});
        const answer = await sendNote('example-owner/sme', 'hello');
        expect(answer).toEqual({ itemId: null, createdAt: null });
    });
});

describe('reasonOfNoteFailure', () => {
    test('a nested code resolves the shared skill.refused sentence', () => {
        const error = new FakeApiError('the server answered 429', 429, null, {
            detail: { code: 'rate_limited' },
        });
        expect(reasonOfNoteFailure(error, t)).toBe(t('skill.refused.rate_limited'));
    });

    test('empty_note and note_too_long each resolve their own sentence', () => {
        const empty = new FakeApiError('m', 400, null, { detail: { code: 'empty_note' } });
        const long = new FakeApiError('m', 400, null, { detail: { code: 'note_too_long' } });
        expect(reasonOfNoteFailure(empty, t)).toBe(t('skill.refused.empty_note'));
        expect(reasonOfNoteFailure(long, t)).toBe(t('skill.refused.note_too_long'));
    });

    test('no nested code falls back to the error message', () => {
        const error = new FakeApiError('the sign in expired', 401, 'signed-out', null);
        expect(reasonOfNoteFailure(error, t)).toBe('the sign in expired');
    });

    test('a plain error not from authFetch still reads its own message', () => {
        expect(reasonOfNoteFailure(new Error('offline'), t)).toBe('offline');
    });
});
