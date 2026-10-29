import { t } from '../../i18n/index.svelte';
import { openSession, openSessions } from '../../../opscenter/api/host';
import * as api from '../api';
import { refusalText } from '../format';
import { data, refresh } from '../page-store.svelte';

export function attachmentHref(runId: string, name: string): string {
  return `/api/v1/automations/runs/${encodeURIComponent(runId)}/attachments/${encodeURIComponent(name)}`;
}

function opened(session: api.CreatedSession, key: string): void {
  openSession(session.id, session.tmux_session ?? null);
  data.notice = t(key);
}

function sessionOf(entry: unknown): { id: string | null; tmux: string | null } {
  if (typeof entry === 'string') return { id: entry, tmux: null };
  const e = (entry ?? {}) as Record<string, unknown>;
  const pick = (...keys: string[]): string | null => keys.map((k) => e[k]).find((v): v is string => typeof v === 'string' && v !== '') ?? null;
  return { id: pick('session_id', 'id'), tmux: pick('tmux_session', 'tmux', 'tmux_name') };
}

export function openRunSessions(list: readonly unknown[] | null | undefined): void {
  const sessions = list ?? [];
  if (sessions.length === 1) {
    const s = sessionOf(sessions[0]);
    if (openSession(s.id, s.tmux)) return;
  }
  openSessions();
}

export async function cancelRun(runId: string): Promise<void> {
  try {
    await api.cancelRun(runId);
  } catch (error) {
    data.notice = refusalText(error);
  }
  await refresh();
}

export async function carryOn(runId: string): Promise<void> {
  try {
    opened(await api.continueRun(runId), 'automations.page.toast.continue_opened');
  } catch (error) {
    data.notice = refusalText(error);
  }
}

export async function fixIt(runId: string, findingId: string): Promise<void> {
  try {
    opened(await api.fixFinding(runId, findingId), 'automations.page.toast.fix_opened');
  } catch (error) {
    data.notice = refusalText(error);
  }
}
