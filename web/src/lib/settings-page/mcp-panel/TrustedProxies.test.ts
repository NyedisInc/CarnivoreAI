/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import McpPanel from '../McpPanel.svelte';
import { checkProxyEntry } from './trusted-proxy';
import { setLocale, t } from '../../i18n/index.svelte';
import type { Fetcher } from './api';

setLocale('en');

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

function server(hosts: string[], puts: string[][]): Fetcher {
    return (async (path: string, init?: { method?: string; body?: string }) => {
        if (path === '/mcp-admin/trusted-proxies') {
            const next = JSON.parse(String(init?.body)).hosts as string[];
            puts.push(next);
            hosts = next;
            return { hosts };
        }
        if (path === '/mcp-admin') {
            return { enabled: true, endpoint: 'http://127.0.0.1:8000/mcp', gate_cross_session_actions: true, guide: 'g',
                tools: [], trusted_proxy_hosts: hosts };
        }
        if (path === '/mcp-admin/agent-tools') return { huddle: false, swarm: true, app_settings: false };
        return { tokens: [] };
    }) as unknown as Fetcher;
}

async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

async function draw(fetcher: Fetcher): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(McpPanel as never, { target, props: { t, fetcher } }) as Record<string, unknown>;
    await settle();
    return target;
}

async function typeAndAdd(target: HTMLElement, text: string): Promise<void> {
    const input = target.querySelector<HTMLInputElement>('[data-mcp="proxy-entry"]')!;
    input.value = text;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    target.querySelector<HTMLButtonElement>('[data-mcp="proxy-add"]')!.click();
    await settle();
}

test('the validator accepts exact addresses and names the reason for the rest', () => {
    expect(checkProxyEntry(' 192.0.2.7 ', [])).toEqual({ ok: true, host: '192.0.2.7' });
    expect(checkProxyEntry('::FFFF:192.0.2.7', ['192.0.2.7'])).toEqual({ ok: false, problem: 'duplicate' });
    expect(checkProxyEntry('2001:DB8::1', [])).toEqual({ ok: true, host: '2001:db8::1' });
    expect(checkProxyEntry('proxy.example.com', [])).toEqual({ ok: false, problem: 'not_ip' });
    expect(checkProxyEntry('192.0.2.0/24', [])).toEqual({ ok: false, problem: 'not_ip' });
    expect(checkProxyEntry('999.1.1.1', [])).toEqual({ ok: false, problem: 'not_ip' });
    expect(checkProxyEntry('127.0.0.1', [])).toEqual({ ok: false, problem: 'not_allowed' });
    expect(checkProxyEntry('::1', [])).toEqual({ ok: false, problem: 'not_allowed' });
    expect(checkProxyEntry('0.0.0.0', [])).toEqual({ ok: false, problem: 'not_allowed' });
    expect(checkProxyEntry('224.0.0.1', [])).toEqual({ ok: false, problem: 'not_allowed' });
    expect(checkProxyEntry('', [])).toEqual({ ok: false, problem: 'empty' });
    expect(checkProxyEntry('192.0.2.9', Array.from({ length: 8 }, (_, i) => `192.0.2.${i + 20}`))).toEqual({ ok: false, problem: 'full' });
});

test('the held hosts are listed, an add sends the whole list, junk and duplicates send nothing', async () => {
    const puts: string[][] = [];
    const target = await draw(server(['192.0.2.7'], puts));
    expect(target.querySelector('[data-mcp-proxy-host="192.0.2.7"]')).not.toBeNull();

    await typeAndAdd(target, 'proxy.example.com');
    expect(target.querySelector('[data-mcp="proxy-problem"]')!.textContent).toContain('not an ip address');
    await typeAndAdd(target, '192.0.2.7');
    expect(target.querySelector('[data-mcp="proxy-problem"]')!.textContent).toContain('already in the list');
    expect(puts).toEqual([]);

    await typeAndAdd(target, '192.0.2.8');
    expect(puts).toEqual([['192.0.2.7', '192.0.2.8']]);
    expect(target.querySelector('[data-mcp-proxy-host="192.0.2.8"]')).not.toBeNull();
    expect(target.querySelector('[data-mcp="proxy-problem"]')).toBeNull();
});

test('remove asks first, then sends the list without that host', async () => {
    const puts: string[][] = [];
    const target = await draw(server(['192.0.2.7', '192.0.2.8'], puts));
    target.querySelector<HTMLButtonElement>('[data-mcp-proxy-host="192.0.2.7"] [data-mcp="proxy-remove"]')!.click();
    await settle();
    expect(puts).toEqual([]);
    target.querySelector<HTMLButtonElement>('[data-mcp="proxy-remove-confirm"]')!.click();
    await settle();
    expect(puts).toEqual([['192.0.2.8']]);
    expect(target.querySelector('[data-mcp-proxy-host="192.0.2.7"]')).toBeNull();
});
