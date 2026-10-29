/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { tick } from 'svelte';

type Reply = { items: unknown[] } | Error;
let reply: Reply = { items: [] };
let failFirst = 0;

vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (path: string) => {
    if (failFirst > 0) { failFirst -= 1; throw new Error('not signed in yet'); }
    if (reply instanceof Error) throw reply;
    return path === '/approvals' ? reply : null;
  },
}));
vi.mock('../../opscenter/api/events.svelte', () => ({ subscribe: () => () => {} }));
vi.mock('../resource-push/boot', () => ({ resourcePush: () => ({ isLive: () => false, pushOrPoll: () => {}, onChange: () => () => {} }) }));

import { approvals, inboxFocus, refreshApprovals } from './approvals.svelte';
import { closePanel, openApprovalFor, wireAskOpeners } from './mount-approvals.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

function item(id: string, session: string): Record<string, unknown> {
  return { id, source: 'dialog', session_id: session, session_name: `name_${session}`, kind: 'permission', question: `q ${id}`, fingerprint: 'f', rows: [{ label: 'yes', role: 'option' }] };
}

const win = window as unknown as { ToastNavigate?: unknown; ToastManager?: unknown; API?: unknown };
const go = vi.fn();
const add = vi.fn();
const dismiss = vi.fn();

function panelCards(): string[] {
  return [...document.querySelectorAll('[data-approval-card]')].map((el) => el.getAttribute('data-approval-card') ?? '');
}

async function settle(): Promise<void> {
  await refreshApprovals();
  await tick();
  await tick();
}

afterEach(async () => {
  if (document.querySelector('[data-approval-inbox]')) {
    reply = { items: [] };
    inboxFocus.session = null;
    closePanel();
  }
  document.body.innerHTML = '';
  reply = { items: [] };
  approvals.items = [];
  approvals.status = 'idle';
  inboxFocus.session = null;
  vi.useRealTimers();
  failFirst = 0;
  win.API = undefined;
  go.mockClear();
  add.mockClear();
  dismiss.mockClear();
});

function install(): void {
  win.ToastNavigate = { go };
  win.ToastManager = { add, dismiss };
}

describe('openApprovalFor', () => {
  test('opens on that session\'s item and never navigates', async () => {
    install();
    reply = { items: [item('dlg:ses_2:b', 'ses_2'), item('dlg:ses_1:a', 'ses_1')] };
    expect(await openApprovalFor('ses_1')).toBe('opened');
    await tick();
    expect(document.querySelector('[data-approval-inbox]')).not.toBeNull();
    expect(panelCards()).toEqual(['dlg:ses_1:a']);
    expect(go).not.toHaveBeenCalled();
    expect(add).not.toHaveBeenCalled();
  });

  test('closes itself when no item is left anywhere, not when only that session is done', async () => {
    install();
    reply = { items: [item('dlg:ses_1:a', 'ses_1'), item('dlg:ses_2:b', 'ses_2')] };
    await openApprovalFor('ses_1');
    await tick();
    reply = { items: [item('dlg:ses_2:b', 'ses_2')] };
    await settle();
    expect(document.querySelector('[data-approval-inbox]')).not.toBeNull();
    expect(panelCards()).toEqual(['dlg:ses_2:b']);
    reply = { items: [] };
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    await settle();
    expect(document.querySelector('[data-approval-inbox]')).not.toBeNull();
    await vi.advanceTimersByTimeAsync(2000);
    await tick();
    expect(document.querySelector('[data-approval-inbox]')).toBeNull();
    expect(document.querySelector('[data-approval-empty]')).toBeNull();
  });

  test('a watcher pass that reads empty between two questions does not close the modal (settle)', async () => {
    install();
    reply = { items: [item('dlg:ses_1:q1', 'ses_1')] };
    await openApprovalFor('ses_1');
    await tick();
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    reply = { items: [] };
    await settle();
    reply = { items: [item('dlg:ses_1:q2', 'ses_1')] };
    await vi.advanceTimersByTimeAsync(2000);
    await tick();
    expect(document.querySelector('[data-approval-inbox]')).not.toBeNull();
    expect(panelCards()).toEqual(['dlg:ses_1:q2']);
  });

  test('stays open between the questions of one multi-question ask (item id changes, session does not)', async () => {
    install();
    reply = { items: [item('dlg:ses_1:q1', 'ses_1')] };
    await openApprovalFor('ses_1');
    await tick();
    reply = { items: [item('dlg:ses_1:q2', 'ses_1')] };
    await settle();
    expect(document.querySelector('[data-approval-inbox]')).not.toBeNull();
    expect(panelCards()).toEqual(['dlg:ses_1:q2']);
  });

  test('an ask already gone opens no popup and says already answered', async () => {
    install();
    reply = { items: [item('dlg:ses_2:b', 'ses_2')] };
    win.API = { listSessions: async () => [{ session: { id: 'ses_1' }, activity_status: 'idle', startup_gate: 'ready' }] };
    expect(await openApprovalFor('ses_1')).toBe('gone');
    await tick();
    expect(document.querySelector('[data-approval-inbox]')).toBeNull();
    expect(add).toHaveBeenCalledTimes(1);
    expect((add.mock.calls[0]![0] as { title: string }).title).toBe('already answered.');
  });

  test('a list that cannot be read opens nothing and answers unknown so the caller can fall back', async () => {
    install();
    reply = new Error('offline');
    expect(await openApprovalFor('ses_1')).toBe('unknown');
    expect(document.querySelector('[data-approval-inbox]')).toBeNull();
    expect(add).not.toHaveBeenCalled();
  });
});

describe('cold start and undecodable items', () => {
  test('a first failed read is retried once before the list is called unreadable', async () => {
    install();
    failFirst = 1;
    reply = { items: [item('dlg:ses_1:a', 'ses_1')] };
    expect(await openApprovalFor('ses_1')).toBe('opened');
  });

  test('?approvals=<id> on a cold start that cannot read the list opens the session instead of nothing', async () => {
    install();
    reply = new Error('offline');
    window.history.replaceState(null, '', '/?approvals=ses_9');
    wireAskOpeners();
    await vi.waitFor(() => expect(go).toHaveBeenCalledWith({ session_id: 'ses_9' }));
    expect(window.location.search).toBe('');
    expect(document.querySelector('[data-approval-inbox]')).toBeNull();
    (window as unknown as { __askOpenersWired?: boolean }).__askOpenersWired = false;
  });

  test('an idle row whose startup gate is ready and has no item is answered: gone, not the terminal', async () => {
    install();
    win.API = { listSessions: async () => [{ session: { id: 'ses_1' }, activity_status: 'idle', startup_gate: 'ready' }] };
    reply = { items: [] };
    expect(await openApprovalFor('ses_1')).toBe('gone');
    expect(add).toHaveBeenCalledTimes(1);
  });

  test('a listing that throws or is unreadable is unknown, not "already answered": the session opens', async () => {
    install();
    reply = { items: [] };
    win.API = { listSessions: async () => { throw new Error('offline'); } };
    expect(await openApprovalFor('ses_1')).toBe('unknown');
    win.API = { listSessions: async () => ({ not: 'an array' }) };
    expect(await openApprovalFor('ses_1')).toBe('unknown');
    win.API = {};
    expect(await openApprovalFor('ses_1')).toBe('unknown');
    expect(add).not.toHaveBeenCalled();
  });

  test('a readable listing without the ask still says already answered', async () => {
    install();
    win.API = { listSessions: async () => [{ session: { id: 'ses_other' }, activity_status: 'question' }] };
    reply = { items: [] };
    expect(await openApprovalFor('ses_1')).toBe('gone');
    expect(add).toHaveBeenCalledTimes(1);
  });

  test('a session on a startup screen with no item opens the session', async () => {
    install();
    win.API = { listSessions: async () => [{ session: { id: 'ses_1' }, activity_status: 'idle', startup_gate: 'awaiting_startup_prompt' }] };
    reply = { items: [] };
    expect(await openApprovalFor('ses_1')).toBe('unknown');
  });

  test('an item the server could not decode while the session still waits opens the session, not "already answered"', async () => {
    install();
    win.API = { listSessions: async () => [{ session: { id: 'ses_1' }, activity_status: 'question' }] };
    reply = { items: [] };
    expect(await openApprovalFor('ses_1')).toBe('unknown');
    expect(add).not.toHaveBeenCalled();
  });
});
