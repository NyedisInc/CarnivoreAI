import { mountPanel, unmountPanel } from '../mount';
import { hostDocument, hostWindow } from '../sessions/env';
import QuestionModal from './QuestionModal.svelte';
import { approvals, inboxFocus, refreshApprovals, startApprovals } from './approvals.svelte';
import { t } from '../i18n/index.svelte';
import type { ApprovalItem } from './approvals-model';

export const APPROVALS_PANEL_ID = 'approvals-panel';

let panelOpen = false;

export function closePanel(): void {
  unmountPanel(APPROVALS_PANEL_ID);
  hostDocument()?.getElementById?.(APPROVALS_PANEL_ID)?.remove?.();
  panelOpen = false;
  inboxFocus.session = null;
}

export function jumpToApproval(item: ApprovalItem): void {
  const nav = (hostWindow() as { ToastNavigate?: { go(toast: { session_id?: string }): Promise<boolean> } } | null)?.ToastNavigate;
  if (item.session_id && nav) void nav.go({ session_id: item.session_id });
  closePanel();
}

function openPanel(): void {
  if (panelOpen) return;
  const doc = hostDocument();
  if (!doc?.body) return;
  let host = doc.getElementById(APPROVALS_PANEL_ID);
  if (!host) {
    host = doc.createElement('div');
    host.id = APPROVALS_PANEL_ID;
    doc.body.appendChild(host);
  }
  panelOpen = mountPanel(APPROVALS_PANEL_ID, QuestionModal as never, { onClose: () => closePanel(), onJump: jumpToApproval } as never) !== null;
}

/* could not be read */
export type OpenApprovalOutcome = 'opened' | 'gone' | 'unknown';

const GONE_CARD_KIND = 'ApprovalGone';
const GONE_CARD_MS = 5000;

type ToastSurface = { add(toast: Record<string, unknown>): void; dismiss?(id: string): unknown };

function sayAlreadyAnswered(): void {
  const surface = (hostWindow() as { ToastManager?: ToastSurface } | null)?.ToastManager;
  if (!surface) return;
  const id = `approval-gone:${Date.now()}:${Math.random().toString(16).slice(2, 8)}`;
  surface.add({
    id, session_id: null, kind: GONE_CARD_KIND, title: t('approvals.already_answered'), body: '',
    session_label: t('approvals.toast.surface'), local: true,
  });
  setTimeout(() => surface.dismiss?.(id), GONE_CARD_MS);
}

type ListingSurface = { listSessions?(): Promise<unknown> };

async function sessionStillWaits(sessionId: string): Promise<boolean> {
  try {
    const rows = await (hostWindow() as { API?: ListingSurface } | null)?.API?.listSessions?.();
    if (!Array.isArray(rows)) return true;
    const row = rows.find((r: { id?: string; session?: { id?: string } }) => (r?.session?.id ?? r?.id) === sessionId) as
      { activity_status?: string; startup_gate?: string } | undefined;
    return !!row && (row.activity_status === 'question' || row.startup_gate === 'awaiting_startup_prompt');
  } catch {
    return true;
  }
}

export async function openApprovalFor(sessionId: string): Promise<OpenApprovalOutcome> {
  startApprovals();
  await refreshApprovals();
  if (approvals.status !== 'ok') await refreshApprovals();
  if (approvals.status !== 'ok') return 'unknown';
  if (!approvals.items.some((item) => item.session_id === sessionId)) {
    if (await sessionStillWaits(sessionId)) return 'unknown';
    sayAlreadyAnswered();
    return 'gone';
  }
  inboxFocus.session = sessionId;
  inboxFocus.seq += 1;
  openPanel();
  if (!panelOpen) {
    inboxFocus.session = null;
    return 'unknown';
  }
  return 'opened';
}

async function openApprovalOrSession(sessionId: string): Promise<void> {
  let outcome: OpenApprovalOutcome = 'unknown';
  try {
    outcome = await openApprovalFor(sessionId);
  } catch {
  }
  if (outcome !== 'unknown') return;
  const nav = (hostWindow() as { ToastNavigate?: { go(toast: { session_id?: string }): Promise<boolean> } } | null)?.ToastNavigate;
  if (nav) void nav.go({ session_id: sessionId });
}

export const OPEN_APPROVAL_MESSAGE = 'carnivore.open-approval';
export const OPEN_APPROVAL_PARAM = 'approvals';

export function wireAskOpeners(): void {
  const win = hostWindow();
  if (!win || (win as { __askOpenersWired?: boolean }).__askOpenersWired) return;
  (win as { __askOpenersWired?: boolean }).__askOpenersWired = true;
  const handle = (data: unknown): void => {
    const msg = data as { type?: unknown; session_id?: unknown } | null;
    if (msg && msg.type === OPEN_APPROVAL_MESSAGE && typeof msg.session_id === 'string' && msg.session_id) {
      void openApprovalOrSession(msg.session_id);
    }
  };
  win.addEventListener('message', (event: MessageEvent) => {
    if (event.source === win && event.origin === win.location.origin) handle(event.data);
  });
  win.navigator?.serviceWorker?.addEventListener?.('message', (event: MessageEvent) => handle(event.data));
  try {
    const url = new URL(win.location.href);
    const sid = url.searchParams.get(OPEN_APPROVAL_PARAM);
    if (sid) {
      url.searchParams.delete(OPEN_APPROVAL_PARAM);
      win.history.replaceState(null, '', url.pathname + url.search + url.hash);
      void openApprovalOrSession(sid);
    }
  } catch {
  }
}
