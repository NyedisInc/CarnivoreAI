/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import JobsTab from './JobsTab.svelte';
import type { PackActivityApi, PackActivityResponse } from './activity-api';
import { JobsStore, type JobsDelta } from './jobs-store.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

function fixture(): PackActivityResponse {
  return {
    days: 7,
    generated_at: 1800000000,
    computers: [
      {
        install_id: 'iid-a', label: 'host-a', is_self: true, state: 'self', online: true,
        cores: 14, cpu_pct: 40, cpu_headroom_cores: 5.5, mem_total_gb: 64, mem_available_gb: 30,
        ram_pct: 53, mem_headroom_gb: 17.2, pegged: false,
        live_agents: 1, live_commands: 0, live_delegated_agents: 0, live_total: 1,
        history_agents: 0, history_commands: 1, history_delegated_agents: 0, history_total: 1,
      },
      {
        install_id: 'iid-b', label: 'host-b', is_self: false, state: 'connected', online: true,
        cores: 10, cpu_pct: 15, cpu_headroom_cores: 7.5, mem_total_gb: 16, mem_available_gb: 8,
        ram_pct: 50, mem_headroom_gb: 6.4, pegged: false,
        live_agents: 0, live_commands: 1, live_delegated_agents: 0, live_total: 1,
        history_agents: 0, history_commands: 0, history_delegated_agents: 0, history_total: 0,
      },
      {
        install_id: 'iid-c', label: 'host-c', is_self: false, state: 'connected', online: true,
        cores: 10, cpu_pct: 8, cpu_headroom_cores: 8.2, mem_total_gb: 16, mem_available_gb: 9,
        ram_pct: 44, mem_headroom_gb: 7.4, pegged: false,
        live_agents: 0, live_commands: 0, live_delegated_agents: 1, live_total: 1,
        history_agents: 0, history_commands: 0, history_delegated_agents: 0, history_total: 0,
      },
    ],
    fleet_aggregate: {
      online_machines: 3, total_machines: 3, total_cores: 34, busy_cores: 7.9,
      fleet_cpu_pct: 23.2, usable_free_cores: 21.2, total_ram_gb: 96, used_ram_gb: 49,
      fleet_ram_pct: 51.0, usable_free_ram_gb: 31.0,
      live_agents_total: 1, live_jobs_total: 2, history_total: 1,
      peer_fanout: { queried: 2, ok: 2, skipped: 0 },
    },
    items: [
      {
        id: 'agent:u-a-1', item_type: 'agent', live: true, status: 'running', tone: 'ok',
        title: 'Cv-PackLoad', project: 'Carnivore', computer_id: 'iid-a', computer_label: 'host-a',
        source_computer_label: null, started_by: { label: 'owner', session_uuid: null, kind: 'owner' },
        started_at: 1799999400, ended_at: null, duration_s: 600, agent_type: 'claude',
        reason: null, session_uuid: 'u-a-1', job_id: null, can_stop: false, origin_scope: 'local',
      },
      {
        id: 'job:j-b-1', item_type: 'command', live: true, status: 'running', tone: 'info',
        title: 'pytest -q tests/pack', project: 'Carnivore', computer_id: 'iid-b', computer_label: 'host-b',
        source_computer_label: 'host-a', started_by: { label: 'Cv-PackLoad', session_uuid: 'u-a-1', kind: 'session' },
        started_at: 1799999880, ended_at: null, duration_s: 120, agent_type: 'command',
        reason: 'host-b had 7.5 cores free', session_uuid: null, job_id: 'j-b-1', can_stop: true, origin_scope: 'local',
      },
      {
        id: 'job:j-p2p-1', item_type: 'delegated_agent', live: true, status: 'running', tone: 'info',
        title: '<img src=x> review diff', project: 'Carnivore', computer_id: 'iid-c', computer_label: 'host-c',
        source_computer_label: 'host-b', started_by: { label: 'host-b-worker (host-b)', session_uuid: null, kind: 'external' },
        started_at: 1799999910, ended_at: null, duration_s: 90, agent_type: 'claude',
        reason: 'host-c was idle', session_uuid: null, job_id: 'j-p2p-1', can_stop: false, origin_scope: 'peer_to_peer',
      },
      {
        id: 'job:j-old-1', item_type: 'command', live: false, status: 'done', tone: 'ok',
        title: 'npm run build', project: 'Carnivore', computer_id: 'iid-a', computer_label: 'host-a',
        source_computer_label: null, started_by: { label: 'Cv-PackLoad', session_uuid: 'u-a-1', kind: 'session' },
        started_at: 1799990000, ended_at: 1799990045, duration_s: 45, agent_type: 'command',
        reason: 'this computer had room', session_uuid: null, job_id: 'j-old-1', can_stop: false, origin_scope: 'local',
      },
    ],
    total_items: 4,
    efficiency: { p50_overhead_s: 11.5, p50_run_s: 45.0, overhead_ratio: 0.2 },
    guard_health: { funnel: { blocked_offload: 8, gave_way: 1 } },
    utilization_history: { pegged_minutes_total: 2, idle_while_peer_pegged_minutes: 0.5 },
    summary: { r3_remote_share: 0.8, p3_miss_share: 0.1, guard_giveways: 1 },
  };
}

let mounted: Array<ReturnType<typeof mount>> = [];
let readMock: ReturnType<typeof vi.fn>;

function makeStore(): JobsStore {
  return new JobsStore({
    api: { list: vi.fn(async () => ({ jobs: [], next_before: null })), stop: vi.fn(async () => ({})) },
    subscribe: () => () => {},
    poll: () => () => {},
    repaint: () => {},
  });
}

async function render(): Promise<HTMLElement> {
  readMock = vi.fn(async () => fixture());
  const api: PackActivityApi = { read: readMock };
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(JobsTab, {
    target,
    props: { store: makeStore(), activity: api, subscribe: (_h: (f: JobsDelta) => void) => () => {} },
  }));
  await vi.advanceTimersByTimeAsync(0);
  flushSync();
  return target;
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => {
  mounted.splice(0).forEach((m) => void unmount(m));
  document.body.replaceChildren();
  vi.useRealTimers();
});

describe('Pack Jobs & Activity Hub (#3328)', () => {
  test('renders KPIs, per-computer distribution cards, live & history lists, starter attribution, and peer-to-peer provenance', async () => {
    const root = await render();
    expect(readMock).toHaveBeenCalledTimes(1);
    expect(root.querySelector('[data-activity="fanout"]')?.textContent).toContain('synced 2 peer(s)');
    expect(root.querySelectorAll('[data-computer]').length).toBe(3);
    expect(root.querySelectorAll('[data-activity="live-list"] [data-activity-row]').length).toBe(3);
    expect(root.querySelectorAll('[data-activity="history-list"] [data-activity-row]').length).toBe(1);
    const p2pRow = root.querySelector('[data-activity-row="job:j-p2p-1"]')!;
    expect(p2pRow.querySelector('[data-activity="computer"]')?.textContent).toBe('host-c ← host-b');
    expect(p2pRow.querySelector('[data-activity="starter"]')?.textContent).toBe('host-b-worker (host-b)');
    expect(p2pRow.querySelector('img')).toBeNull();
    expect(p2pRow.textContent).toContain('<img src=x> review diff');
  });

  test('clicking anywhere on a computer card filters both sections to that machine, clicking again clears, and All computers dropdown is removed (#3334)', async () => {
    const root = await render();
    expect(root.querySelector('select[aria-label="Filter by computer"]')).toBeNull();
    const hostBBody = root.querySelector('[data-computer="iid-b"] .pa-bars') as HTMLElement;
    hostBBody.click();
    flushSync();
    expect(root.querySelector('[data-computer="iid-b"]')?.getAttribute('data-selected')).toBe('true');
    expect(root.querySelectorAll('[data-activity="live-list"] [data-activity-row]').length).toBe(1);
    expect(root.querySelector('[data-activity="history-empty"]')).not.toBeNull();
    hostBBody.click();
    flushSync();
    expect(root.querySelectorAll('[data-activity="live-list"] [data-activity-row]').length).toBe(3);
    expect(root.querySelectorAll('[data-activity="history-list"] [data-activity-row]').length).toBe(1);
  });
});
