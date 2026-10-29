/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { expect, test } from 'vitest';
import AgentTabMarks from './AgentTabMarks.svelte';
import SessionRow from './SessionRow.svelte';
import { buildRowPlan } from './row-plan';
import type { RowHost } from './row-host';

const wrapper = {
    tmux_session: 'cloude_a',
    session: { id: 'ses_1' },
    running_model: 'opus',
    running_model_tier: 5,
    running_model_effort: 'xhigh',
    spectator_expires_at: '2026-10-03T00:00:00Z',
    agent_update: { running: '1.0', installed: '1.1', ready: true },
};

test('a tab draws the drawer row model colour, share mark and update icon', () => {
    (globalThis as Record<string, unknown>).SessionRowMenuIcons = { svg: () => '<svg data-u="1"></svg>' };
    const row = document.body.appendChild(document.createElement('div'));
    const plan = buildRowPlan({ name: 'cloude_a', session_id: 'ses_1', ...wrapper } as never, 'cozy', undefined, null, {} as RowHost);
    const a = mount(SessionRow, { target: row, props: { p: plan as never } });
    const tab = document.body.appendChild(document.createElement('div'));
    const b = mount(AgentTabMarks, { target: tab, props: { info: wrapper, part: 'lead' } });
    const c = mount(AgentTabMarks, { target: tab, props: { info: wrapper, part: 'tail' } });
    flushSync();
    const m = (el: Element) => el.querySelector('.session-sidebar-row-model')!;
    const bare = (el: Element) => el.className.replace(/ svelte-\w+/, '');
    expect(bare(m(tab))).toBe(bare(m(row)));
    expect(m(tab).getAttribute('data-model-tier')).toBe('5');
    expect(m(tab).getAttribute('title')).toBe(m(row).getAttribute('title'));
    expect(tab.querySelector('.session-sidebar-row-share')!.getAttribute('title'))
        .toBe(row.querySelector('.session-sidebar-row-share')!.getAttribute('title'));
    expect(tab.querySelector('.oc-tab-update')!.getAttribute('title')).toContain('1.0 → 1.1');
    expect(tab.querySelector('.session-row-gauge, [class*="limit-gauge"]')).toBeNull();
    for (const x of [a, b, c]) unmount(x);
    row.remove(); tab.remove();
});
