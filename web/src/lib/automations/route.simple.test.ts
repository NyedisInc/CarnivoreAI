import { describe, expect, test, vi } from 'vitest';

vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ pushOrPoll: () => () => {} }) }));
vi.mock('../listing-push/boot', () => ({ whenListingPushBooted: () => {} }));
vi.mock('./api', async (orig) => ({
  ...(await orig<typeof import('./api')>()),
  listSessionRecords: vi.fn(async () => []),
  listFeed: vi.fn(async () => ({ runs: [], total: 0, next_before: null })),
}));

import { data, openInAdvanced } from './page-store.svelte';
import { parseRoute } from './route';
import { AUTOMATIONS_TABS, effectiveAdvancedTab, effectiveTab } from './tabs';

describe('fragments', () => {
  test.each([
    ['#automations', null],
    ['#automations/sessions', { kind: 'sessions' }],
    ['#automations/advanced', { kind: 'advanced' }],
    ['#automations/sessions/run/run_1', { kind: 'feed_run', runId: 'run_1' }],
    ['#automations/run/run_2', { kind: 'run', runId: 'run_2' }],
    ['#automations/session/abc-123', { kind: 'session', uuid: 'abc-123' }],
    ['#automations/edit/auto_1', { kind: 'edit', id: 'auto_1' }],
    ['#automations/new/session/abc-123', { kind: 'new', prefill: { kind: 'session', id: 'abc-123' } }],
    ['#automations/new/project/7', { kind: 'new', prefill: { kind: 'project', id: 7 } }],
  ])('%s', (hash, want) => {
    expect(parseRoute(hash)).toEqual(want);
  });
});

describe('tabs', () => {
  test('the top tabs are the three, and a remembered huddle reads as automations', () => {
    expect([...AUTOMATIONS_TABS]).toEqual(['automations', 'sessions', 'advanced']);
    for (const id of AUTOMATIONS_TABS) expect(effectiveTab(id)).toBe(id);
    expect(effectiveTab('huddle')).toBe('automations');
    expect(effectiveAdvancedTab('advanced')).toBe('automations');
    expect(effectiveAdvancedTab('sessions')).toBe('sessions');
  });
});

describe('openInAdvanced', () => {
  test('a run lands in the run feed with that run open', () => {
    data.top = 'sessions';
    data.drawer = { kind: 'run', id: 'run_9' };
    openInAdvanced('run', 'run_9');
    expect(data.top).toBe('advanced');
    expect(data.tab).toBe('sessions');
    expect(data.feedRunId).toBe('run_9');
    expect(data.drawer).toBeNull();
  });

  test('an automation lands in the table with its row selected and the pane open', () => {
    data.top = 'automations';
    data.drawer = { kind: 'automation', id: 'auto_5' };
    openInAdvanced('automation', 'auto_5');
    expect(data.top).toBe('advanced');
    expect(data.tab).toBe('automations');
    expect(data.selectedId).toBe('auto_5');
    expect(data.paneOpen).toBe(true);
    expect(data.drawer).toBeNull();
  });
});
