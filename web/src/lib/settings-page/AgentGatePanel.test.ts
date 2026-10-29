/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import AgentGatePanel from './AgentGatePanel.svelte';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

let handle: Record<string, unknown> | null = null;

afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('the settings block shows the bolt, what it is for, where it lives, the risk line and a link to the plugin settings', async () => {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(AgentGatePanel, { target, props: { t, fetcher: (async () => ({ gate_cross_session_actions: true })) as never } }) as Record<string, unknown>;
    flushSync();
    await tick();

    const block = target.querySelector('[data-agent-gate="beast"]')!;
    expect(block.querySelector('svg')).not.toBeNull();
    expect(block.querySelector('[data-agent-gate="beast-label"]')!.textContent).toBe('beast mode');
    for (const part of ['what', 'where']) {
        expect(block.querySelector(`[data-agent-gate="beast-${part}"]`)!.textContent!.length).toBeGreaterThan(40);
    }
    const risk = block.querySelector('[data-agent-gate="beast-risk"]')!;
    expect(risk.textContent).toMatch(/nobody is checking/);
    expect(block.querySelector('[data-agent-gate="beast-toggle"]')).toBeNull();
    expect(block.querySelector('[data-agent-gate="beast-settings"]')!.getAttribute('href')).toBe('#settings/advanced/beast_mode');
});
