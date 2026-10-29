import { approvals, startApprovals } from '../approvals/approvals.svelte';
import { isQuestionItem, type ApprovalItem } from '../approvals/approvals-model';
import { holdAggregate, huddle, startTaskManager } from '../../cplugs/huddle/huddle.svelte';
import { alertCenter, startAlertCenter } from '../app-alerts/alerts.svelte';
import { t } from '../i18n/index.svelte';
import { acquireScheduledRuns, releaseScheduledRuns } from '../../opscenter/api/scheduled-runs.svelte';
import { badgeOf } from './bell-badge';
import { alertRows, approvalRows, failedAutomationRows, taskManagerRows, type AttentionRow } from './rows';

let runs = $state.raw<ReturnType<typeof acquireScheduledRuns> | null>(null);

let holders = 0;

export function startAttentionSources(): () => void {
  startApprovals();
  startTaskManager();
  startAlertCenter();
  const releaseTaskManager = holdAggregate();
  runs = acquireScheduledRuns();
  holders += 1;
  let released = false;
  return () => {
    if (released) return;
    released = true;
    releaseTaskManager();
    releaseScheduledRuns();
    holders -= 1;
    if (holders === 0) runs = null;
  };
}

export function attentionRows(): AttentionRow[] {
  return rowsFor(approvals.items);
}

export function bellRows(): AttentionRow[] {
  return rowsFor(approvals.items.filter((item) => !isQuestionItem(item)));
}

export function bellBadge(): ReturnType<typeof badgeOf> {
  return badgeOf(bellRows());
}

function rowsFor(items: readonly ApprovalItem[]): AttentionRow[] {
  return [
    ...approvalRows(items),
    ...taskManagerRows(huddle.groups),
    ...alertRows(alertCenter.alerts, t),
    ...failedAutomationRows(runs?.data?.runs ?? []),
  ];
}

export function attentionUnread(): boolean {
  return approvals.status === 'idle' && huddle.status === 'idle' && alertCenter.status === 'idle';
}

export function attentionBroken(): boolean {
  return approvals.status === 'error' && huddle.status === 'error' && alertCenter.status !== 'ok';
}
