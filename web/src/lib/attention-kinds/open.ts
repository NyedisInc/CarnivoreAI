import { openApprovalFor } from '../approvals/mount-approvals.svelte';
import { openAppAlerts } from '../app-alerts/alert-panel.svelte';
import { openTaskManagerItem } from '../task-manager-reveal/reveal';
import { openAutomationEdit } from '../automations/schedule-prefill';
import type { AttentionTarget } from './rows';

export interface OpenOutcome {
  failedKey: string;
  failedText: string;
}

export async function openAttention(target: AttentionTarget): Promise<OpenOutcome> {
  const ok: OpenOutcome = { failedKey: '', failedText: '' };
  switch (target.source) {
    case 'approval':
      return (await openApprovalFor(target.sessionId)) === 'unknown' ? { failedKey: 'opscenter.cell.questions.open_failed', failedText: '' } : ok;
    case 'alert':
      openAppAlerts();
      return ok;
    case 'automation':
      return openAutomationEdit(target.automationId) ? ok : { failedKey: 'opscenter.cell.questions.open_failed', failedText: '' };
    case 'huddle': {
      const why = await openTaskManagerItem(target.list, target.itemId);
      return { failedKey: '', failedText: why || '' };
    }
  }
}
