/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

type Call = { path: string; method: string; body: unknown };
const server = vi.hoisted(() => ({ calls: [] as Call[], entries: [] as unknown[], extra: {} as Record<string, unknown> }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetchBlob: async (path: string) => { server.calls.push({ path, method: 'GET', body: null }); return new Blob(['png'], { type: 'image/png' }); },
    authFetch: async (path: string, init: RequestInit = {}) => {
      const method = init.method ?? 'GET';
      server.calls.push({ path, method, body: init.body && !(init.body instanceof FormData) ? JSON.parse(String(init.body)) : null });
      if (path.startsWith('/sessions/upload-file')) return { path: '/proj/.cloude_uploads/ab12cd34-paste.png', filename: 'ab12cd34-paste.png', size: 3 };
      if (path === '/swarm/agents/7' && method === 'GET') {
        return { id: 7, display_name: 'Loki', rank: 'feature', state: 'asleep', thread_key: '12', session_id: 'ses_9', tmux_session: null, ...server.extra };
      }
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: server.entries, cursor: null };
      if (path === '/swarm/agents/7/export') return new File(['PK'], 'project-agent-craft.zip', { type: 'application/zip' });
      if (path === '/swarm/agents/7/messages') return { message_ref: 'huddle:msg:1', outcome: 'waking' };
      return {};
    },
  };
});

import { kindOf, metaFor } from '../../../opscenter/engine/meta';
import { viewersOf } from '../../../opscenter/engine/model';
import { resetLayout } from '../../../opscenter/engine/model';
import { entryFor } from '../../../opscenter/cells/registry';
import { manifestForSlot } from '../../../opscenter/widgets/core-manifests';
import { checkFit, fitsForSlot, suggestedSizes } from '../../../opscenter/widgets/fits';
import { standardSizes } from '../../../opscenter/widgets/standard-sizes';
import { META } from '../../../opscenter/engine/meta';
import { validateManifest } from '../../../opscenter/widgets/validate';
import { resourcePush } from '../../../lib/resource-push/boot';
import { registerCplugWidgets } from '../../host/widgets';
import { huddleCplug } from '../index';
import ChatWidget from './ChatWidget.svelte';
import ChatWidgetHost from './ChatWidgetHost.svelte';
import { agentIdOf, chatSlotId, menuActions, menuHasTurnOff } from './chat-model';

// jsdom has no popover API; the one item menu shows its levels through it (#2613).
const popoverProto = HTMLElement.prototype as unknown as Record<string, unknown>;
popoverProto.showPopover ??= function () {};
popoverProto.hidePopover ??= function () {};

const SLOT = chatSlotId(7);
let app: object | null = null;

const card = (id: number, status: string, kind = 'question', waits = status === 'question') => ({
  kind: 'card', id: `item:${id}`, at: 1, card: kind, waits_on_owner: waits,
  item: { id, list: 'agent:7', text: `ship ${id}`, note: '', position: 1, created_by: 'claude', state: 'open', kind, revision: 1, created_seq: 1, seq: 1, deleted: false, status, thread: [] },
});

async function mountChat(props: Record<string, unknown> = {}): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: SLOT, ...props } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

beforeEach(() => {
  server.calls.length = 0;
  server.entries = [];
  server.extra = {};
  resourcePush().store.hello({ resource_topics: ['swarm_agent'] });
  registerCplugWidgets(huddleCplug);
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  delete (window as unknown as { App?: unknown }).App;
  vi.restoreAllMocks();
});

describe('files on the composer', () => {
  test('a pasted image uploads through the terminal route, shows a chip, and the send carries its path', async () => {
    const host = await mountChat();
    const box = host.querySelector('textarea') as HTMLTextAreaElement;
    const image = new File(['abc'], 'paste.png', { type: 'image/png' });
    const paste = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(paste, 'clipboardData', { value: { files: [image], items: [], types: ['Files'] } });
    box.dispatchEvent(paste);
    expect(paste.defaultPrevented).toBe(true);
    await vi.waitFor(() => expect(host.querySelector('[data-task-manager-pending-file][data-state="ready"]')).not.toBeNull());
    expect(server.calls.some((c) => c.path === '/sessions/upload-file?session_id=ses_9' && c.method === 'POST')).toBe(true);
    box.value = 'look at this';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(server.calls.some((c) => c.path === '/swarm/agents/7/messages' && c.method === 'POST')).toBe(true));
    expect(server.calls.find((c) => c.path === '/swarm/agents/7/messages')?.body).toEqual({ text: 'look at this\n/proj/.cloude_uploads/ab12cd34-paste.png' });
  });
});

describe('the placement line', () => {
  test('says where the pack placed the agent and why, only when a reason was recorded', async () => {
    server.extra = { host_key: 'peer-1', host_label: 'studio', placement_reason: 'most headroom after its reserve' };
    const host = await mountChat();
    expect(host.querySelector('[data-chat-placed]')!.textContent!.trim()).toBe('placed on studio: most headroom after its reserve');
  });

  test('a local agent reads this computer, and an agent with no recorded reason shows no line', async () => {
    server.extra = { host_key: 'local', placement_reason: 'light job stays home' };
    expect((await mountChat()).querySelector('[data-chat-placed]')!.textContent).toContain('placed on this computer: light job stays home');
    unmount(app!);
    app = null;
    server.extra = { host_key: 'peer-1', host_label: 'studio', placement_reason: null };
    expect((await mountChat()).querySelector('[data-chat-placed]')).toBeNull();
  });
});

describe('the seam registers the widget for the engine', () => {
  test('a slot of the kind is an instance with a record, a binding and a manifest that validates', () => {
    expect(kindOf(SLOT as never)).toBe('huddle.chat');
    expect(metaFor(SLOT as never, META).id).toBe(SLOT);
    expect(entryFor(SLOT as never)?.component).toBe(ChatWidgetHost);
    const manifest = manifestForSlot(SLOT as never);
    expect(manifest?.id).toBe('huddle.chat');
    expect(manifest?.instancing).toBe('per-target');
    expect(validateManifest(manifest).ok).toBe(true);
    expect(agentIdOf(SLOT)).toBe(7);
    expect(agentIdOf('huddle.chat:agent:0')).toBeNull();
  });

  test('a chat is not a live pane: it never counts against the terminal cap', () => {
    const layout = resetLayout(META, 'terminal');
    const withChat = { ...layout, rows: layout.rows.map((row, i) => (i === 0 ? { ...row, slots: [...row.slots, { id: SLOT, fr: 1 }] } : row)) };
    expect(viewersOf(withChat as never)).toEqual(viewersOf(layout));
  });
});

describe('fits at every standard size', () => {
  test('home and terminal: no size draws the not-available plate', () => {
    const fits = fitsForSlot(SLOT as never);
    expect(fits).not.toBeNull();
    const meta = metaFor(SLOT as never, META);
    for (const zone of ['home', 'terminal'] as const) {
      for (const size of standardSizes({ minPx: meta.minPx, minHeight: meta.minHeight }, zone, null, suggestedSizes(fits!))) {
        const verdict = checkFit(fits!, size.h === null ? null : { width: size.w, height: size.h });
        expect({ zone, size: size.name, ok: verdict.ok }).toEqual({ zone, size: size.name, ok: true });
      }
    }
  });
});

describe('the one keyed store', () => {
  test('reads the agent and its conversation, rereads on its own frames only, and runs no timer', async () => {
    const interval = vi.spyOn(globalThis, 'setInterval');
    server.entries = [card(1, 'question')];
    const host = await mountChat();
    const reads = () => server.calls.filter((c) => c.method === 'GET' && c.path.startsWith('/swarm/agents/7')).length;
    expect(reads()).toBe(2);
    expect(host.querySelector('[data-chat-card="question"]')).not.toBeNull();
    resourcePush().store.frame({ topics: ['swarm_agent:8'] });
    await tick();
    expect(reads()).toBe(2);
    resourcePush().store.frame({ topics: ['swarm_agent:7'] });
    await vi.waitFor(() => expect(reads()).toBe(4));
    expect(interval).not.toHaveBeenCalled();
    unmount(app!, { outro: false });
    app = null;
    resourcePush().store.frame({ topics: ['swarm_agent:7'] });
    await tick();
    expect(reads()).toBe(4);
  });

  test('the waiting on me filter keeps only what waits', async () => {
    server.entries = [card(1, 'question'), card(2, 'done', 'done'), { kind: 'owner', id: 'msg:3', at: 2, text: 'go' },
      card(4, 'review', 'review'), card(5, 'question', 'question', false)];
    const host = await mountChat();
    expect(host.querySelectorAll('[data-chat-entry]').length).toBe(5);
    expect(host.querySelector('.hdc-filter')?.textContent).toContain('1');
    (host.querySelector('.hdc-filter') as HTMLButtonElement).click();
    flushSync();
    expect(host.querySelectorAll('[data-chat-entry]').length).toBe(1);
  });
});

describe('the order box and the menu', () => {
  test('an order posts to the agent and wakes it', async () => {
    const host = await mountChat();
    const box = host.querySelector('.hdc-input') as HTMLTextAreaElement;
    box.value = 'build the thing';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    (host.querySelector('.hdc-send') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(server.calls.some((c) => c.path === '/swarm/agents/7/messages' && c.method === 'POST')).toBe(true));
    expect(server.calls.find((c) => c.path === '/swarm/agents/7/messages')?.body).toEqual({ text: 'build the thing' });
  });

  test('an asleep agent offers wake fresh and resume, an awake one sleep', () => {
    expect(menuActions('asleep')).toEqual(['wake_fresh', 'resume']);
    expect(menuActions('awake')).toEqual(['sleep']);
    expect(menuActions('torn_down')).toEqual([]);
  });

  test('the menu offers export, which downloads the craft-only zip under the name the server sent', async () => {
    const made: Blob[] = [];
    URL.createObjectURL = (blob: Blob | MediaSource) => (made.push(blob as Blob), 'blob:craft');
    URL.revokeObjectURL = () => {};
    const names: string[] = [];
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { names.push(this.download); });
    const host = await mountChat();
    host.querySelector('[data-chat-bar]')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
    flushSync();
    expect(host.querySelector('[role="menu"]')).toBeNull();
    (document.querySelector('[data-node="export"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(names).toEqual(['project-agent-craft.zip']));
    expect(server.calls.some((c) => c.path === '/swarm/agents/7/export' && c.method === 'GET')).toBe(true);
    expect(made[0]!.type).toBe('application/zip');
  });

  test('turn off is offered to every live agent but Alpha, and its fold-out confirm calls the route', async () => {
    expect(menuHasTurnOff('asleep', 'project')).toBe(true);
    expect(menuHasTurnOff('awake', 'company')).toBe(true);
    expect(menuHasTurnOff('awake', 'alpha')).toBe(false);
    expect(menuHasTurnOff('torn_down', 'project')).toBe(false);
    const confirmSpy = vi.spyOn(window, 'confirm');
    const host = await mountChat();
    host.querySelector('[data-chat-bar]')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
    flushSync();
    const off = document.querySelector('[data-node="turn-off-agent"]') as HTMLButtonElement;
    expect(off.classList.contains('acm-item--danger')).toBe(true);
    off.click();
    flushSync();
    const yes = document.querySelector('[data-node="turn-off-confirm"]') as HTMLButtonElement;
    expect(yes.querySelector('.acm-label')?.textContent).toBe('turn off Loki? its memory stays in the repo');
    expect(server.calls.some((c) => c.path.endsWith('/turn-off'))).toBe(false);
    yes.click();
    await vi.waitFor(() => expect(server.calls.some((c) => c.path === '/swarm/agents/7/turn-off' && c.method === 'POST')).toBe(true));
    expect(confirmSpy).not.toHaveBeenCalled();
  });

  test('the bar draws no menu button; a right click on the strip and Shift+F10 open the one item menu (#2613, #2567)', async () => {
    const host = await mountChat();
    expect(host.querySelector('[data-chat-menu]')).toBeNull();
    expect(host.querySelector('.hdc-menu-key')).toBeNull();
    expect(host.querySelector('[aria-haspopup="menu"]')).toBeNull();
    const rows = (): string[] => [...document.querySelectorAll('#item-menu-host [data-node]')].map((n) => n.getAttribute('data-node') ?? '');
    const bar = host.querySelector('[data-chat-bar]') as HTMLElement;
    bar.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
    flushSync();
    const fromClick = rows();
    expect(fromClick).toContain('export');
    expect(fromClick).toContain('turn-off-agent');
    expect(host.querySelector('[role="menu"]')).toBeNull();
    bar.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true }));
    flushSync();
    bar.dispatchEvent(new KeyboardEvent('keydown', { key: 'F10', shiftKey: true, bubbles: true, cancelable: true }));
    flushSync();
    expect(rows()).toEqual(fromClick);
  });

  test('open terminal is hidden where the window has no terminal, shown where it has one', async () => {
    const openMenu = (root: HTMLElement): void => { root.querySelector('[data-chat-bar]')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 })); flushSync(); };
    let host = await mountChat();
    openMenu(host);
    expect(document.querySelector('[data-node="export"]')).not.toBeNull();
    expect(document.querySelector('[data-node="terminal"]')).toBeNull();
    unmount(app!, { outro: false });
    app = null;
    (window as unknown as { App: unknown }).App = { returnToExistingTerminal: async () => {} };
    host = await mountChat();
    openMenu(host);
    expect(document.querySelector('[data-node="terminal"]')).not.toBeNull();
  });
});

describe('the widget form offers the drawer chat and Tasks Viewer switch (WIDGETTABS)', () => {
  test('the registered widget draws the tab row; Tasks Viewer shows the lists and chat brings the conversation back', async () => {
    document.body.innerHTML = '<div id="host"></div>';
    const component = entryFor(SLOT as never)?.component as typeof ChatWidget;
    app = mount(component, { target: document.getElementById('host') as HTMLElement, props: { instance: SLOT } });
    const host = document.getElementById('host') as HTMLElement;
    await vi.waitFor(() => expect(host.querySelector('[data-chat-state="ok"]')).not.toBeNull());
    const tabs = [...host.querySelectorAll('[data-agent-drawer-tab]')].map((el) => el.getAttribute('data-agent-drawer-tab'));
    expect(tabs).toEqual(['chat', 'tasks']);
    (host.querySelector('[data-agent-drawer-tab="tasks"]') as HTMLButtonElement).click();
    await tick();
    expect(host.querySelector('[data-agent-drawer-tasks]')).not.toBeNull();
    expect(host.querySelector('[data-chat-state]')).toBeNull();
    (host.querySelector('[data-agent-drawer-tab="chat"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(host.querySelector('[data-chat-state="ok"]')).not.toBeNull());
    expect(host.querySelector('[data-agent-drawer-tasks]')).toBeNull();
  });
  test('an image chip shows a thumbnail, a click opens it full size, and removing the chip revokes the url', async () => {
    const made: string[] = [];
    const revoked: string[] = [];
    URL.createObjectURL = (() => { const u = `blob:thumb-${made.length}`; made.push(u); return u; }) as never;
    URL.revokeObjectURL = ((u: string) => { revoked.push(u); }) as never;
    const host = await mountChat();
    const box = host.querySelector('textarea') as HTMLTextAreaElement;
    const paste = new Event('paste', { bubbles: true, cancelable: true });
    Object.defineProperty(paste, 'clipboardData', { value: { files: [new File(['abc'], 'paste.png', { type: 'image/png' })], items: [], types: ['Files'] } });
    box.dispatchEvent(paste);
    await vi.waitFor(() => expect(host.querySelector('[data-task-manager-thumb] img')).not.toBeNull());
    expect(host.querySelector('[data-task-manager-thumb] img')?.getAttribute('src')).toBe(made[0]);
    (host.querySelector('[data-task-manager-thumb]') as HTMLElement).click();
    await vi.waitFor(() => expect(document.querySelector('[data-task-manager-preview-image]')?.getAttribute('src')).toBe(made[0]));
    document.querySelector('[data-task-manager-preview-image]')!.closest('[role="dialog"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await vi.waitFor(() => expect(document.querySelector('[data-task-manager-preview-image]')).toBeNull());
    (host.querySelector('[data-task-manager-pending-remove]') as HTMLElement).click();
    await vi.waitFor(() => expect(revoked).toContain(made[0]));
  });
  test('a sent message with an uploads picture path shows a thumbnail instead of the path line, and a click opens it full size', async () => {
    URL.createObjectURL = (() => 'blob:sent-0') as never;
    URL.revokeObjectURL = (() => {}) as never;
    const path = '/proj/.cloude_uploads/ab12cd34-paste.png';
    server.entries = [{ kind: 'owner', id: 'msg:1', at: 1, text: `look at this\n${path}\n/proj/.cloude_uploads/ab12cd34-notes.txt` }];
    const host = await mountChat();
    await vi.waitFor(() => expect(host.querySelector('[data-chat-sent-images] [data-task-manager-thumb] img')).not.toBeNull());
    expect(server.calls.some((c) => c.path === `/sessions/ses_9/upload-image?path=${encodeURIComponent(path)}`)).toBe(true);
    const text = host.querySelector('[data-chat-entry="owner"]')?.textContent ?? '';
    expect(text).toContain('look at this');
    expect(text).toContain('ab12cd34-notes.txt');
    expect(text).not.toContain('paste.png');
    (host.querySelector('[data-chat-sent-images] [data-task-manager-thumb]') as HTMLElement).click();
    await vi.waitFor(() => expect(document.querySelector('[data-task-manager-preview-image]')?.getAttribute('src')).toBe('blob:sent-0'));
  });
});
