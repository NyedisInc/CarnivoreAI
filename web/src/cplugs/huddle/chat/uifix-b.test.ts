/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const server = vi.hoisted(() => ({ entries: [] as unknown[] }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/swarm/agents/7') return { id: 7, display_name: 'Loki', rank: 'feature', state: 'awake', thread_key: '12', session_id: 'ses_9', tmux_session: null };
      if (path.startsWith('/swarm/agents/7/conversation')) return { entries: server.entries, cursor: null };
      return {};
    },
  };
});

import { resourcePush } from '../../../lib/resource-push/boot';
import ChatWidget from './ChatWidget.svelte';
import ChatCard from './ChatCard.svelte';
import { cardVariant, chatSlotId } from './chat-model';
import type { HuddleItem } from '../huddle-model';

// jsdom has no popover API; the one item menu shows its levels through it (#2613).
const popoverProto = HTMLElement.prototype as unknown as Record<string, unknown>;
popoverProto.showPopover ??= function () {};
popoverProto.hidePopover ??= function () {};

let app: object | null = null;

async function mountChat(): Promise<HTMLElement> {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(ChatWidget, { target: document.getElementById('host') as HTMLElement, props: { instance: chatSlotId(7) } });
  await vi.waitFor(() => expect(document.querySelector('[data-chat-state="ok"]')).not.toBeNull());
  return document.getElementById('host') as HTMLElement;
}

beforeEach(() => {
  server.entries = [];
  resourcePush().store.hello({ resource_topics: ['swarm_agent'] });
});

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
});

describe('buttons keep their own looks', () => {
  test('turn off is the danger class, send is quiet until there is text and then the confirm class, never the danger one', async () => {
    const host = await mountChat();
    const send = host.querySelector('.hdc-send') as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    expect(send.classList.contains('oc-btn--confirm')).toBe(false);
    expect(send.classList.contains('oc-btn--danger')).toBe(false);
    const input = host.querySelector('.hdc-input') as HTMLTextAreaElement;
    input.value = 'go';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    expect(send.classList.contains('oc-btn--confirm')).toBe(true);
    host.querySelector('[data-chat-bar]')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 10 }));
    flushSync();
    (document.querySelector('[data-node="turn-off-agent"]') as HTMLButtonElement).click();
    flushSync();
    const yes = document.querySelector('[data-node="turn-off-confirm"]') as HTMLButtonElement;
    expect(yes.classList.contains('acm-item--danger')).toBe(true);
    expect(yes.classList.contains('oc-btn--confirm')).toBe(false);
  });
});

describe('a card the system closed is never an approval', () => {
  function closed(ref: string): HuddleItem {
    return { id: 5, list: 'agent:7', text: 'asks', title: 'trust this folder?', note: '', position: 1, created_by: 'claude', state: 'done',
             kind: 'question', revision: 1, created_seq: 1, seq: 1, deleted: false, status: 'done', thread: [], swarm_ref: ref } as unknown as HuddleItem;
  }

  test('closed: reads closed, an owner approval still reads approved', () => {
    expect(cardVariant(closed('closed:trust:4:ab'))).toBe('closed');
    document.body.innerHTML = '<div id="host"></div>';
    app = mount(ChatCard, { target: document.getElementById('host') as HTMLElement, props: { item: closed('closed:trust:4:ab'), card: 'question', agentName: 'Loki' } });
    flushSync();
    const text = document.body.textContent ?? '';
    expect(document.querySelector('[data-chat-decision]')?.getAttribute('data-chat-decision')).toBe('closed');
    expect(text).not.toMatch(/approved/);
    unmount(app, { outro: false });
    app = mount(ChatCard, { target: document.getElementById('host') as HTMLElement, props: { item: closed('done:1'), card: 'done', agentName: 'Loki' } });
    flushSync();
    expect(document.querySelector('[data-chat-decision]')?.textContent).toBe('approved');
  });
});

describe('agent text is markdown built from nodes', () => {
  test('bold and headings render, raw html and script stay text', async () => {
    server.entries = [{ kind: 'agent', id: 'msg:2', at: 2, text: '## Order\n**The work:** done <script>window.x=1</script> <img src="http://e/x.png">' }];
    const host = await mountChat();
    const body = host.querySelector('.hdc-msg--agent .hdc-md') as HTMLElement;
    expect(body.querySelector('h2')?.textContent).toBe('Order');
    expect(body.querySelector('strong')?.textContent).toBe('The work:');
    expect(body.querySelector('script, img')).toBeNull();
    expect(body.textContent).toContain('<script>window.x=1</script>');
    expect(body.textContent).not.toContain('**');
  });
});
