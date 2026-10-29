/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

const h = vi.hoisted(() => ({ focus: vi.fn(async (): Promise<string | null> => null) }));

vi.mock('../task-manager-reveal/task-manager-open', () => ({ focusTaskManagerItem: h.focus }));
vi.mock('../session-rail/rail-store.svelte', () => ({ railStores: { side: { items: [] }, bottom: { items: [] } } }));
vi.mock('../drawer-zone/zone-store.svelte', () => ({ drawerZone: { items: [] } }));
vi.mock('../approvals/mount-approvals.svelte', () => ({ openApprovalFor: vi.fn() }));
vi.mock('../app-alerts/alert-panel.svelte', () => ({ openAppAlerts: vi.fn() }));

import { sidebarTabs } from '../dynamic-tabs/tab-store.svelte';
import { t } from '../i18n/index.svelte';
import { openAttention } from './open';

const TARGET = { source: 'huddle', list: '12', itemId: 345 } as const;

afterEach(() => {
  document.body.innerHTML = '';
  h.focus.mockClear();
});

describe('a huddle row opens in a Task Manager widget, never the Swarm tab', () => {
  test('a widget on screen: the item is focused, nothing failed, the Swarm tab stays unselected', async () => {
    const widget = document.createElement('div');
    widget.setAttribute('data-task-manager-all-cell', '');
    document.body.appendChild(widget);
    const outcome = await openAttention(TARGET);
    expect(outcome).toEqual({ failedKey: '', failedText: '' });
    expect(h.focus).toHaveBeenCalledWith('12', 345);
    expect(sidebarTabs.active()).not.toBe('huddle');
  });

  test('no widget placed: one sentence says to add one, nothing is written, the Swarm tab stays unselected', async () => {
    const outcome = await openAttention(TARGET);
    expect(outcome).toEqual({ failedKey: '', failedText: t('opscenter.cell.task_list.no_tm') });
    expect(h.focus).not.toHaveBeenCalled();
    expect(sidebarTabs.active()).not.toBe('huddle');
  });
});
