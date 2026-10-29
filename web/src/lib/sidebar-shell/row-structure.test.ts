/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { setDrawerEnv } from '../drawer/env';
import { timerChip } from '../timers/timers';
import BrowserRow from './BrowserRow.svelte';
import { canonicalDom, loadLegacyDrawer, type LegacyWindow } from './legacy-fixture';
import { rowHost } from './row-host';
import { buildRowPlan } from './row-plan';
import SessionRow from './SessionRow.svelte';

const NOW = Date.UTC(2026, 9, 21, 12, 0, 0);

let w: LegacyWindow;
const mounted: Array<{ app: ReturnType<typeof mount>; target: HTMLElement }> = [];

beforeAll(() => {
    vi.useFakeTimers({ now: NOW, toFake: ['Date'] });
    w = loadLegacyDrawer();
    w.CloudeWeb = {
        ...(w.CloudeWeb || {}),
        timerChip,
        autoSleep: { isKeptAwake: (name: string) => name.startsWith('cloude_full') },
    };
});
afterAll(() => { vi.useRealTimers(); setDrawerEnv(null); });
afterEach(() => {
    for (const m of mounted) { unmount(m.app); m.target.remove(); }
    mounted.length = 0;
    setDrawerEnv(null);
});

const epochAgo = (ago: number): number => Math.floor(NOW / 1000) - ago;
const isoIn = (ms: number): string => new Date(NOW + ms).toISOString();

function full(over: Record<string, unknown> = {}): Record<string, unknown> {
    return {
        name: 'cloude_full', label: 'full', created_by_cloude: true, status: 'working_subagent', agent_family: 'claude',
        session_id: 'ses_full', session_uuid: 'su-full', kind: 'agent', is_pinned: true, is_this_tab: false,
        subagents_running: 2, subagents_total: 3, workflow_active: true, background_open: 1, parked_summary: 'npm test',
        timers_live: 2, timers_next_fire_at: isoIn(90_000),
        automations_state: 'warning', automations_total: 2, automations_enabled: 1,
        automations_next: [{ name: 'nightly', next_fire_at: epochAgo(-3600) }],
        spectator_expires_at: isoIn(86_400_000), host_key: 'studio', host_label: 'Studio', host_state: 'degraded',
        automation: { automation_id: 'a1', run_id: 'r1', name: 'nightly' }, task_lead: true,
        running_model: 'claude-opus-5', running_model_tier: 5, running_model_effort: 'xhigh',
        created_at_epoch: epochAgo(7200), last_work_at: new Date(NOW - 600_000).toISOString(),
        context_pct: 42, ...over,
    };
}

function draw(r: Record<string, unknown>, density: string, band?: string): string {
    const target = document.body.appendChild(document.createElement('div'));
    const p = buildRowPlan(r as never, density, band, null, rowHost());
    const app = p.type === 'browser'
        ? mount(BrowserRow, { target, props: { p } })
        : mount(SessionRow, { target, props: { p: p as never } });
    flushSync();
    mounted.push({ app, target });
    return canonicalDom(target);
}

function cases(): string {
    const out: string[] = [];
    const add = (name: string, html: string): void => { out.push(`=== ${name}`, html); };
    const iconsOn = { agents: true, shells: true, timers: true, automations: true, cup: true, pin: true, menu: true, context: true };
    setDrawerEnv({ PreferenceBridge: { read: () => ({ compact: iconsOn }) } });
    add('compact, every icon on', draw(full(), 'compact', 'pinned'));
    add('compact, dnd, archived, asleep with a wake clock', draw(full({
        name: 'cloude_full_asleep', task_lead: false, do_not_disturb: true, archived: true, asleep: true, status: 'idle',
        next_wake_at: epochAgo(-7200), spectator_expires_at: null,
    }), 'compact'));
    add('compact, closed', draw(full({ name: 'cloude_closed', closed: true, status: 'idle' }), 'compact'));
    add('compact, update ready', draw(full({
        name: 'cloude_update', agent_update: { ready: true, running: '2.1.1', installed: '2.1.2' },
    }), 'compact'));
    add('compact, mcp dropped', draw(full({
        name: 'cloude_mcp', mcp_health: { dropped: [{ name: 'carnivore', source: 'server' }] },
    }), 'compact'));
    add('compact, dead', draw(full({ name: 'cloude_dead', status: 'dead' }), 'compact'));
    add('compact, hostile name', draw({ name: 'x"><b>y', status: 'idle', agent_family: 'claude' }, 'compact'));
    setDrawerEnv({ PreferenceBridge: { read: () => ({ compact: { menu: false, pin: false, cup: false } }) } });
    add('compact, kebab dimmed, pin and cup hidden', draw(full({ name: 'cloude_dim' }), 'compact'));
    setDrawerEnv(null);
    add('cozy, live body', draw(full(), 'cozy'));
    add('cozy, dead body', draw(full({ name: 'cloude_dead', status: 'dead' }), 'cozy'));
    add('detailed, live body', draw(full(), 'detailed'));
    add('detailed, dead body', draw(full({ name: 'cloude_dead', status: 'dead' }), 'detailed'));
    add('cozy shell (no body)', draw(full({ name: 'cloude_shell', agent_family: 'shell', status: 'idle' }), 'cozy'));
    add('detailed shell (no body)', draw(full({ name: 'cloude_shell', agent_family: 'shell', status: 'idle' }), 'detailed'));
    add('browser, live', draw({ name: 'browser:0001', kind: 'browser', status: 'live', browser_id: 7, url: 'https://example.com/a', is_pinned: true }, 'compact'));
    add('browser, page', draw({ name: 'browser:0002', kind: 'browser', page: true, label: 'notes', url: 'https://example.com/p' }, 'compact'));
    add('browser, file, dirty', draw({ name: 'browser:0003', kind: 'browser', file: true, dirty: true, path: '/a/b.ts', label: 'b.ts' }, 'compact'));
    return out.join('\n');
}

describe('drawer row chips and controls', () => {
    it('draw the recorded DOM for every chip, action and trigger', async () => {
        await expect(cases()).toMatchFileSnapshot('./__goldens__/row-structure.html');
    });
});
