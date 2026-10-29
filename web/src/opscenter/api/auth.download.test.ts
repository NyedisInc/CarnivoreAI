import { afterEach, expect, test, vi } from 'vitest';
import { authFetch, authFetchBlob } from './auth.svelte';

afterEach(() => vi.unstubAllGlobals());

function zip(headers: Record<string, string>): void {
    vi.stubGlobal('fetch', () => Promise.resolve(new Response('PK', { status: 200, headers: { 'Content-Type': 'application/zip', ...headers } })));
}

test('the filename comes from Content-Disposition', async () => {
    zip({ 'Content-Disposition': 'attachment; filename="project-agent-craft.zip"' });
    const got = await authFetch<Blob>('/swarm/agents/2/export');
    expect(got).toBeInstanceOf(File);
    expect((got as File).name).toBe('project-agent-craft.zip');
});

test('no Content-Disposition leaves a plain Blob', async () => {
    zip({});
    const got = await authFetch<Blob>('/swarm/agents/2/export');
    expect(got instanceof File).toBe(false);
    expect(got.type).toBe('application/zip');
});

test('a named non-JSON file (a huddle attachment) comes back as a File, a named JSON export stays parsed', async () => {
    vi.stubGlobal('fetch', () => Promise.resolve(new Response('png-bytes', { status: 200, headers: { 'Content-Type': 'image/png', 'Content-Disposition': 'inline; filename="a.png"' } })));
    const file = await authFetch<Blob>('/cplugs/huddle/items/1/files/49759e95');
    expect(file).toBeInstanceOf(File);
    expect((file as File).name).toBe('a.png');
    expect(file.type).toBe('image/png');
    vi.stubGlobal('fetch', () => Promise.resolve(new Response('{"a":1}', { status: 200, headers: { 'Content-Type': 'application/json', 'Content-Disposition': 'attachment; filename="x.json"' } })));
    expect(await authFetch<{ a: number }>('/themes/x/export')).toEqual({ a: 1 });
});

test('authFetchBlob answers a stored .json file byte for byte, and a file that is not valid JSON too (issue #1788)', async () => {
    const exact = '{ "big": 9007199254740993,\n  "k": 1, "k": 2 }\n';
    vi.stubGlobal('fetch', () => Promise.resolve(new Response(exact, { status: 200, headers: { 'Content-Type': 'application/json', 'Content-Disposition': 'attachment; filename="data.json"' } })));
    expect(await (await authFetchBlob('/cplugs/huddle/items/1/files/49759e95')).text()).toBe(exact);
    vi.stubGlobal('fetch', () => Promise.resolve(new Response('not json {', { status: 200, headers: { 'Content-Type': 'application/json' } })));
    expect(await (await authFetchBlob('/cplugs/huddle/items/1/files/49759e95')).text()).toBe('not json {');
    vi.stubGlobal('fetch', () => Promise.resolve(new Response(exact, { status: 200, headers: { 'Content-Type': 'application/json' } })));
    expect(JSON.stringify(await authFetch<unknown>('/cplugs/huddle/items/1/files/49759e95'))).not.toBe(exact);
});

test('a 204 answer has its empty body drained, so the browser does not cancel the request unread (ERR_ABORTED on POST /ui/activity)', async () => {
    const res = new Response(null, { status: 204 });
    const drain = vi.spyOn(res, 'arrayBuffer');
    vi.stubGlobal('fetch', () => Promise.resolve(res));
    expect(await authFetch<undefined>('/ui/activity', { method: 'POST', body: '{}' })).toBeUndefined();
    expect(drain).toHaveBeenCalledTimes(1);
});
