import { t } from '../../i18n/index.svelte';
import * as api from '../api';
import { refusalText } from '../format';
import { feed } from '../feed-store.svelte';
import { data, openDrawer, openNew, refresh, reloadFeed, setTab, setTop } from '../page-store.svelte';
import { startFromTemplate } from '../list-state.svelte';
import type { Template } from '../logic/templates';

export const overview = $state({
  find: '',
  expanded: {} as Record<string, boolean>,
  pending: {} as Record<string, boolean>,
});

export async function setEnabled(a: api.Automation, next: boolean): Promise<void> {
  const id = a.automation_id;
  if (id in overview.pending) return;
  overview.pending = { ...overview.pending, [id]: next };
  data.notice = '';
  const settle = (): void => {
    const { [id]: _done, ...rest } = overview.pending;
    overview.pending = rest;
  };
  try {
    await api.updateAutomation(id, a.revision, { enabled: next });
    data.notice = t(next ? 'automations.page.toast.switched_on' : 'automations.page.toast.switched_off', { name: a.name });
  } catch (error) {
    settle();
    data.notice = refusalText(error);
  }
  try {
    await refresh();
  } finally {
    settle();
  }
}

export function jumpToSessions(which: 'needs' | 'failed'): void {
  data.pressed = which === 'failed' ? { failed_24h: true } : { waiting_on_you: true };
  setTop('sessions');
  if (feed.status !== 'idle') void reloadFeed();
}

export function openCard(id: string): void {
  openDrawer('automation', id);
}

function inWorkbench(open: () => void): void {
  setTop('advanced');
  setTab('automations');
  open();
}

export function startBlank(): void {
  inWorkbench(() => openNew());
}

export function startTemplate(tpl: Template): void {
  inWorkbench(() => startFromTemplate(tpl));
}
