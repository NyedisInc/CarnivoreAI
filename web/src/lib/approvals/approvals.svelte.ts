import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import { subscribe } from '../../opscenter/api/events.svelte';
import { resourcePush } from '../resource-push/boot';
import { t } from '../i18n/index.svelte';
import {
  answerBody, APPROVALS_FRAME, refusalReason, type ApprovalItem, type AskAnswerBody, type DialogChoice,
} from './approvals-model';

export const POLL_MS = 30_000;
const COALESCE_MS = 250;

export const approvals = $state<{
  items: ApprovalItem[];
  status: 'idle' | 'ok' | 'error';
  notices: Record<string, string>;
}>({ items: [], status: 'idle', notices: {} });

export function questionPending(): boolean {
  return approvals.items.length > 0;
}

export function noticeKey(item: ApprovalItem): string {
  return item.source === 'dialog' ? `dialog:${item.session_id ?? item.id}` : item.id;
}

function pruneNotices(): void {
  const live = new Set(approvals.items.map(noticeKey));
  const kept = Object.fromEntries(Object.entries(approvals.notices).filter(([key]) => live.has(key)));
  if (Object.keys(kept).length !== Object.keys(approvals.notices).length) approvals.notices = kept;
}

export const inboxFocus = $state<{ session: string | null; seq: number }>({ session: null, seq: 0 });

let started = false;
let pending: ReturnType<typeof setTimeout> | null = null;

export async function refreshApprovals(): Promise<void> {
  try {
    const body = await authFetch<{ items: ApprovalItem[] }>('/approvals');
    approvals.items = Array.isArray(body.items) ? body.items : [];
    approvals.status = 'ok';
    pruneNotices();
  } catch {
    approvals.status = 'error';
  }
}

function scheduleRefresh(): void {
  if (pending) return;
  pending = setTimeout(() => {
    pending = null;
    void refreshApprovals();
  }, COALESCE_MS);
}

export function startApprovals(): void {
  if (started) return;
  started = true;
  subscribe(APPROVALS_FRAME, () => {
    if (!resourcePush().isLive('approvals')) scheduleRefresh();
  });
  subscribe('events.hello', () => scheduleRefresh());
  void refreshApprovals();
  resourcePush().pushOrPoll(scheduleRefresh, POLL_MS, ['approvals']);
}

function explain(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = refusalReason(error.payload);
    if (reason) {
      const key = `approvals.reason.${reason}`;
      const text = t(key);
      return text === key ? reason : text;
    }
    return error.message;
  }
  return t('approvals.failed');
}

async function decide(item: ApprovalItem, run: () => Promise<unknown>): Promise<boolean> {
  const key = noticeKey(item);
  approvals.notices = Object.fromEntries(Object.entries(approvals.notices).filter(([k]) => k !== key));
  try {
    await run();
    return true;
  } catch (error) {
    approvals.notices = { ...approvals.notices, [key]: explain(error) };
    return false;
  } finally {
    await refreshApprovals();
  }
}

export function answerDialog(item: ApprovalItem, choice: DialogChoice): Promise<boolean> {
  const id = encodeURIComponent(item.session_id ?? '');
  return decide(item, () => authFetch(`/sessions/${id}/dialog/answer`, {
    method: 'POST', body: JSON.stringify(answerBody(item, choice)),
  }));
}

/* in order and */
export function answerAll(item: ApprovalItem, answers: AskAnswerBody[]): Promise<boolean> {
  const id = encodeURIComponent(item.session_id ?? '');
  return decide(item, () => authFetch(`/sessions/${id}/dialog/answer-all`, {
    method: 'POST', body: JSON.stringify({ questions_fingerprint: item.questions_fingerprint ?? '', answers }),
  }));
}

export function decideAgentAction(item: ApprovalItem, approve: boolean, typed?: string): Promise<boolean> {
  const id = encodeURIComponent(item.id);
  const init: RequestInit = approve && typed !== undefined
    ? { method: 'POST', body: JSON.stringify({ typed }) } : { method: 'POST' };
  return decide(item, () => authFetch(`/agent-actions/${id}/${approve ? 'approve' : 'deny'}`, init));
}
