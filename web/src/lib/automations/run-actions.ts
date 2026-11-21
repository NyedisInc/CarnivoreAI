import { t } from '../i18n/index.svelte';
import { openSession, openSessions } from '../../opscenter/api/host';
import { authFetchBlob } from '../../opscenter/api/auth.svelte';
import * as api from './api';
import { refusalText } from './format';
import { data, refresh } from './page-store.svelte';

export function attachmentPath(runId: string, name: string): string {
  return `/automations/runs/${encodeURIComponent(runId)}/attachments/${encodeURIComponent(name)}`;
}

export function attachmentHref(runId: string, name: string): string {
  return `/api/v1${attachmentPath(runId, name)}`;
}

export async function downloadAttachment(runId: string, name: string): Promise<void> {
  try {
    const blob = await authFetchBlob(attachmentPath(runId, name));
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = name;
    link.rel = 'noopener';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
  } catch (error) {
    data.notice = refusalText(error);
  }
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

export async function cancelRun(runId: string, alsoRefresh?: () => Promise<void>): Promise<void> {
  try {
    await api.cancelRun(runId);
  } catch (error) {
    data.notice = refusalText(error);
  }
  await Promise.all([refresh(), alsoRefresh?.()]);
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
