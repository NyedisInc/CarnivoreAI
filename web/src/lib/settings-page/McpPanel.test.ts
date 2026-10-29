/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import McpPanel from './McpPanel.svelte';
import { MCP_FEATURES } from './mcp-panel/features';
import McpToolList from '../user-guide/McpToolList.svelte';
import { GUIDE_SECTIONS } from '../user-guide/guide-content';
import { setLocale, t } from '../i18n/index.svelte';
import type { Fetcher } from './mcp-panel/api';

setLocale('en');

const status = {
    enabled: true, endpoint: 'http://127.0.0.1:8000/mcp', gate_cross_session_actions: true, guide: 'g',
    tools: [
        { name: 'sessions_list', description: 'every live session', write: false },
        { name: 'session_stop', description: 'stop one session', write: true },
    ],
};
const fetcher = (async (path: string) => (path === '/mcp-admin' ? status : { tokens: [] })) as unknown as Fetcher;

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

async function draw(component: unknown): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(component as never, { target, props: { t, fetcher } }) as Record<string, unknown>;
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    return target;
}

test('the settings block shows no tool rows, only a link to the docs mcp section with the count', async () => {
    const target = await draw(McpPanel);
    expect(target.querySelector('[data-mcp="endpoint"]')).not.toBeNull();
    expect(target.textContent).not.toContain('sessions_list');
    expect(target.textContent).not.toContain('read from the server');
    const link = target.querySelector<HTMLAnchorElement>('[data-mcp="tools-link"]')!;
    expect(link.getAttribute('href')).toBe('#docs/mcp');
    expect(link.textContent).toContain('2 mcp tools');
});

test('the docs mcp section exists and its tool list names every tool, marking the write one', async () => {
    expect(GUIDE_SECTIONS.some((s) => s.id === 'mcp')).toBe(true);
    const target = await draw(McpToolList);
    const rows = [...target.querySelectorAll('[data-docs-mcp-tool]')];
    expect(rows.map((r) => r.getAttribute('data-docs-mcp-tool'))).toEqual(['sessions_list', 'session_stop']);
    expect(rows[1]!.textContent).toContain('write');
    expect(rows[0]!.textContent).toContain('every live session');
});

function recorder(enabled: boolean, puts: string[]): Fetcher {
    return (async (path: string, init?: { method?: string; body?: string }) => {
        if (init?.method === 'PUT') { puts.push(String(init.body)); return { enabled: false }; }
        return path === '/mcp-admin' ? { ...status, enabled } : { tokens: [] };
    }) as unknown as Fetcher;
}

async function drawWith(f: Fetcher): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(McpPanel as never, { target, props: { t, fetcher: f } }) as Record<string, unknown>;
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    return target;
}

test('mcp server off: a warning lists every feature that stops working and says new sessions lose the tools', async () => {
    const target = await drawWith(recorder(false, []));
    const warn = target.querySelector('[data-mcp="off-warning"]')!;
    expect(warn).not.toBeNull();
    const ids = [...warn.querySelectorAll('[data-mcp-feature]')].map((el) => el.getAttribute('data-mcp-feature'));
    expect(ids).toEqual([...MCP_FEATURES]);
    expect(warn.textContent).toContain('crosstalk');
    expect(warn.textContent).toContain('new and restarted sessions no longer get the carnivore tools');
});

test('mcp server on: switching it off shows the same list first and writes nothing until confirmed', async () => {
    const puts: string[] = [];
    const target = await drawWith(recorder(true, puts));
    expect(target.querySelector('[data-mcp="off-warning"]')).toBeNull();
    target.querySelector<HTMLElement>('[data-mcp="switch"]')!.click();
    flushSync();
    const confirm = target.querySelector('[data-mcp="off-confirm"]')!;
    expect(confirm.querySelectorAll('[data-mcp-feature]').length).toBe(MCP_FEATURES.length);
    expect(puts).toEqual([]);
    target.querySelector<HTMLElement>('[data-mcp="off-keep"]')!.click();
    flushSync();
    expect(target.querySelector('[data-mcp="off-confirm"]')).toBeNull();
    target.querySelector<HTMLElement>('[data-mcp="switch"]')!.click();
    flushSync();
    target.querySelector<HTMLElement>('[data-mcp="off-go"]')!.click();
    await tick();
    expect(puts).toEqual(['{"enabled":false}']);
});

async function mintWith(name: string, days: string | null): Promise<{ bodies: Record<string, unknown>[]; target: HTMLElement }> {
    const bodies: Record<string, unknown>[] = [];
    const f = (async (path: string, init?: { method?: string; body?: string }) => {
        if (init?.method === 'POST') {
            bodies.push(JSON.parse(String(init.body)));
            return { token: { id: 't1', name }, secret: 's3cret' };
        }
        return path === '/mcp-admin' ? status : { tokens: [] };
    }) as unknown as Fetcher;
    const target = await drawWith(f);
    const type = (sel: string, value: string): void => {
        const el = target.querySelector<HTMLInputElement>(sel)!;
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
    };
    type('[data-mcp="name"]', name);
    if (days !== null) type('[data-mcp="days"]', days);
    flushSync();
    target.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
    return { bodies, target };
}

test('minting with a typed expiry sends the number of days and shows no error', async () => {
    const { bodies, target } = await mintWith('ci', '30');
    expect(bodies).toEqual([{ name: 'ci', scope: 'read', expires_in_days: 30 }]);
    expect(target.textContent).not.toContain('is not a function');
    expect(target.querySelector<HTMLInputElement>('[data-mcp="days"]')!.value).toBe('');
});

test('minting with the expiry field cleared after typing sends null', async () => {
    const { bodies, target } = await mintWith('ci', '');
    expect(bodies).toEqual([{ name: 'ci', scope: 'read', expires_in_days: null }]);
    expect(target.textContent).not.toContain('is not a function');
});
