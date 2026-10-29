/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import AgentToolChecks from './AgentToolChecks.svelte';
import { setLocale, t } from '../../i18n/index.svelte';
import type { Fetcher } from './api';

setLocale('en');

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

function server(puts: string[]): Fetcher {
    let held = { huddle: false, swarm: true, app_settings: false };
    return (async (path: string, init?: { method?: string; body?: string }) => {
        expect(path).toBe('/mcp-admin/agent-tools');
        if (init?.method === 'PUT') {
            puts.push(String(init.body));
            held = { ...held, ...JSON.parse(String(init.body)) };
        }
        return held;
    }) as unknown as Fetcher;
}

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) await Promise.resolve();
    await tick();
    flushSync();
}

test('three lowercase checkboxes with hints show the defaults: huddle off, swarm on, app settings off', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(AgentToolChecks as never, { target, props: { t, fetcher: server([]) } }) as Record<string, unknown>;
    await settle();
    const box = (id: string): HTMLInputElement => target.querySelector<HTMLInputElement>(`[data-mcp="${id}"]`)!;
    const huddle = box('agent-task-manager').closest('label')!;
    const swarm = box('agent-swarm').closest('label')!;
    const settings = box('agent-app-settings').closest('label')!;
    expect(box('agent-task-manager').type).toBe('checkbox');
    expect(box('agent-task-manager').checked).toBe(false);
    expect(box('agent-swarm').checked).toBe(true);
    expect(box('agent-app-settings').checked).toBe(false);
    expect(huddle.textContent).toContain('task manager tools for agents');
    expect(swarm.textContent).toContain('swarm tools for agents');
    expect(settings.textContent).toContain('app settings tools for agents');
    expect(huddle.querySelector('.oc-pick__hint')?.textContent).toBeTruthy();
    expect(swarm.querySelector('.oc-pick__hint')?.textContent).toBeTruthy();
    const hint = settings.querySelector('.oc-pick__hint')?.textContent ?? '';
    expect(hint).toContain('pins and groups');
    expect(hint).toContain('/mcp reconnect');
});

test('a click writes only that switch and shows what the server answered', async () => {
    const puts: string[] = [];
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(AgentToolChecks as never, { target, props: { t, fetcher: server(puts) } }) as Record<string, unknown>;
    await settle();
    target.querySelector<HTMLElement>('[data-mcp="agent-task-manager"]')!.click();
    await settle();
    expect(puts).toEqual(['{"huddle":true}']);
    expect(target.querySelector<HTMLInputElement>('[data-mcp="agent-task-manager"]')!.checked).toBe(true);
    target.querySelector<HTMLElement>('[data-mcp="agent-swarm"]')!.click();
    await settle();
    expect(puts).toEqual(['{"huddle":true}', '{"swarm":false}']);
    expect(target.querySelector<HTMLInputElement>('[data-mcp="agent-swarm"]')!.checked).toBe(false);
    target.querySelector<HTMLElement>('[data-mcp="agent-app-settings"]')!.click();
    await settle();
    expect(puts).toEqual(['{"huddle":true}', '{"swarm":false}', '{"app_settings":true}']);
    expect(target.querySelector<HTMLInputElement>('[data-mcp="agent-app-settings"]')!.checked).toBe(true);
});
