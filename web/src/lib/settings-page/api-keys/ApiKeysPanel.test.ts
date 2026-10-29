/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import ApiKeysPanel from './ApiKeysPanel.svelte';
import { setLocale, t } from '../../i18n/index.svelte';
import type { ApiKey, Fetcher } from './api';

setLocale('en');

const SECRET = 'cak_' + 'Q7W2E9R4T6Y1U8I3O5P0ZXCVBNMLKJHGFDSAq7w2e9r';

interface Call { readonly path: string; readonly method: string; readonly body?: string }

function server(rows: ApiKey[], calls: Call[]): Fetcher {
    return (async (path: string, init?: { method?: string; body?: string }) => {
        const method = init?.method ?? 'GET';
        calls.push({ path, method, body: init?.body });
        if (method === 'POST') {
            const name = JSON.parse(String(init?.body)).name as string;
            const key: ApiKey = { id: 'key_new', name, display_prefix: SECRET.slice(0, 10), created_at: 1, last_used_at: null, revoked_at: null };
            rows.unshift(key);
            return { key, secret: SECRET };
        }
        if (method === 'DELETE') {
            const id = decodeURIComponent(path.split('/').pop()!);
            const i = rows.findIndex((r) => r.id === id);
            rows[i] = { ...rows[i]!, revoked_at: 2 };
            return { revoked: rows[i] };
        }
        return { keys: rows.map((r) => ({ ...r })) };
    }) as unknown as Fetcher;
}

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function draw(fetcher: Fetcher): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(ApiKeysPanel as never, { target, props: { t, fetcher } }) as Record<string, unknown>;
    await settle();
    return target;
}

const row = (id: string, name: string, extra: Partial<ApiKey> = {}): ApiKey =>
    ({ id, name, display_prefix: 'cak_AbCdEf', created_at: 1_700_000_000, last_used_at: null, revoked_at: null, ...extra });

test('the list renders every key with its prefix, and a revoked key has no revoke button', async () => {
    const target = await draw(server([row('key_a', 'crate sync'), row('key_b', 'old', { revoked_at: 1_700_000_100 })], []));
    const keys = [...target.querySelectorAll('[data-api-keys="key"]')];
    expect(keys.map((k) => k.getAttribute('data-api-key-id'))).toEqual(['key_a', 'key_b']);
    expect(keys[0]!.textContent).toContain('crate sync');
    expect(keys[0]!.querySelector('[data-api-keys="prefix"]')!.textContent).toBe('cak_AbCdEf');
    expect(keys[0]!.querySelector('[data-api-keys="revoke"]')).not.toBeNull();
    expect(keys[1]!.querySelector('[data-api-keys="revoke"]')).toBeNull();
    expect(keys[1]!.querySelector('[data-api-keys="revoked"]')).not.toBeNull();
    expect(target.textContent).not.toContain('settings.api_keys.');
});

test('an empty list says so', async () => {
    const target = await draw(server([], []));
    expect(target.querySelector('[data-api-keys="none"]')).not.toBeNull();
});

test('a new key is revealed once with a copy button and the will-not-be-shown-again line, then gone', async () => {
    const calls: Call[] = [];
    const target = await draw(server([], calls));
    const input = target.querySelector<HTMLInputElement>('[data-api-keys="name"]')!;
    input.value = 'crate sync';
    input.dispatchEvent(new Event('input'));
    await settle();
    target.querySelector<HTMLButtonElement>('[data-api-keys="create"]')!.click();
    await settle();
    expect(calls.some((c) => c.method === 'POST' && c.path === '/api-keys' && JSON.parse(c.body!).name === 'crate sync')).toBe(true);
    const reveal = target.querySelector('[data-api-keys="secret"]')!;
    expect(reveal).not.toBeNull();
    expect(reveal.querySelector('[data-api-keys="secret-value"]')!.textContent).toContain(SECRET);
    expect(reveal.querySelector('[data-api-keys="copy-secret"]')).not.toBeNull();
    expect(reveal.textContent).toContain('will not be shown again');
    expect(target.querySelector('[data-api-keys="key"]')!.textContent).not.toContain(SECRET);
    target.querySelector<HTMLButtonElement>('[data-api-keys="dismiss-secret"]')!.click();
    await settle();
    expect(target.querySelector('[data-api-keys="secret"]')).toBeNull();
    expect(target.innerHTML).not.toContain(SECRET);
});

test('revoke warns first, cancel calls nothing, the danger button calls DELETE for that key', async () => {
    const calls: Call[] = [];
    const target = await draw(server([row('key_a', 'crate sync')], calls));
    target.querySelector<HTMLButtonElement>('[data-api-keys="revoke"]')!.click();
    await settle();
    expect(target.querySelector('[data-api-keys="revoke-warn"]')).not.toBeNull();
    target.querySelector<HTMLButtonElement>('[data-api-keys="revoke-cancel"]')!.click();
    await settle();
    expect(calls.filter((c) => c.method === 'DELETE')).toEqual([]);

    target.querySelector<HTMLButtonElement>('[data-api-keys="revoke"]')!.click();
    await settle();
    const confirm = target.querySelector<HTMLButtonElement>('[data-api-keys="revoke-confirm"]')!;
    expect(confirm.getAttribute('data-btn')).toBe('danger');
    confirm.click();
    await settle();
    expect(calls.filter((c) => c.method === 'DELETE').map((c) => c.path)).toEqual(['/api-keys/key_a']);
    expect(target.querySelector('[data-api-keys="revoked"]')).not.toBeNull();
});
