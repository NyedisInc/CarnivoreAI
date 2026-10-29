import { afterEach, expect, test, vi } from 'vitest';
import { ApiError, authFetch } from './auth.svelte';

afterEach(() => vi.unstubAllGlobals());

function answer(status: number, body: unknown): void {
    vi.stubGlobal('fetch', () => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })));
}

test('the inner detail of a coded refusal is the message, and the body rides along as the payload', async () => {
    answer(501, { detail: { code: 'summary_not_available', detail: 'summary restore needs a model call' } });
    const error = await authFetch('/time-machine/points/p/restore').catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toBe('summary restore needs a model call');
    expect((error as ApiError).status).toBe(501);
});

test('a plain string detail still wins, and a body with nothing to say falls back to the status sentence', async () => {
    answer(404, { detail: 'no restore point p9 for this session' });
    expect(((await authFetch('/x').catch((e: unknown) => e)) as ApiError).message).toBe('no restore point p9 for this session');
    answer(500, {});
    expect(((await authFetch('/x').catch((e: unknown) => e)) as ApiError).status).toBe(500);
});

test('a code the string catalog knows shows the catalog sentence, not the server text (wave H3)', async () => {
    answer(500, { detail: { code: 'not_found', detail: 'raw text /Users/x/secret' } });
    const error = (await authFetch('/x').catch((e: unknown) => e)) as ApiError;
    expect(error.message).toBe('that item was not found.');
    expect(error.code).toBe('not_found');
});

test('a code the catalog does not know keeps the server sentence', async () => {
    answer(409, { detail: { code: 'no_such_catalog_code', detail: 'the server sentence' } });
    const error = (await authFetch('/x').catch((e: unknown) => e)) as ApiError;
    expect(error.message).toBe('the server sentence');
});
