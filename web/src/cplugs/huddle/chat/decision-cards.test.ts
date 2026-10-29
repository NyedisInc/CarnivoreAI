/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const writes = vi.hoisted(() => ({ approved: [] as number[], replies: [] as string[] }));

vi.mock('../huddle.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../huddle.svelte')>();
  return {
    ...real,
    setApproved: async (item: { id: number }) => { writes.approved.push(item.id); return true; },
    reply: async (_item: unknown, text: string) => { writes.replies.push(text); return true; },
  };
});

import ChatCard from './ChatCard.svelte';
import { decisionKeys } from './chat-model';
import HuddleReply from '../HuddleReply.svelte';
import type { HuddleItem } from '../huddle-model';

let app: object | null = null;

function card(ref: string, state = 'open'): HuddleItem {
  return { id: 5, list: 'agent:7', text: 'Loki is starting in repo. trust it, or not now to leave it asleep.', title: 'trust this folder?', note: '', position: 1,
           created_by: 'claude', state, kind: 'question', revision: 1, created_seq: 1, seq: 1, deleted: false, status: state === 'open' ? 'question' : state,
           thread: [], swarm_ref: ref } as unknown as HuddleItem;
}

function draw(component: unknown, props: Record<string, unknown>): HTMLElement {
  document.body.innerHTML = '<div id="host"></div>';
  app = mount(component as never, { target: document.getElementById('host') as HTMLElement, props });
  flushSync();
  return document.getElementById('host') as HTMLElement;
}

afterEach(() => {
  if (app) unmount(app, { outro: false });
  app = null;
  document.body.innerHTML = '';
  writes.approved.length = 0;
  writes.replies.length = 0;
});

describe('decision cards', () => {
  test('the pairs follow the swarm_ref prefix, never the kind', () => {
    expect(decisionKeys(card('trust:4:ab'))?.yes).toMatch(/decide\.trust$/);
    expect(decisionKeys(card('held:1:ab'))?.no).toMatch(/decide\.deny$/);
    expect(decisionKeys(card('suggest:3'))?.yes).toMatch(/decide\.approve$/);
    expect(decisionKeys(card('question:3'))).toBeNull();
  });

  test('a choice card offers yes and no, and one marked :no offers only no', () => {
    expect(decisionKeys(card('choice:4:ab'))?.yes).toMatch(/decide\.yes$/);
    expect(decisionKeys(card('choice:4:ab:no'))?.yes).toBeNull();
    const host = draw(ChatCard, { item: card('choice:4:ab:no'), card: 'question', agentName: 'Loki' });
    expect([...host.querySelectorAll('[data-chat-receipt] button')].map((b) => b.textContent)).toEqual(['no']);
    expect(host.querySelector('[data-decide="yes"]')).toBeNull();
  });

  test('the trust card shows trust and not now and no reply box; trust approves, not now replies', async () => {
    const host = draw(ChatCard, { item: card('trust:4:ab'), card: 'question', agentName: 'Loki' });
    const labels = [...host.querySelectorAll('[data-chat-receipt] button')].map((b) => b.textContent);
    expect(labels).toEqual(['not now', 'trust']);
    expect(host.querySelector('[data-huddle-reply]')).toBeNull();
    (host.querySelector('[data-decide="yes"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(host.querySelector('[data-chat-decision="yes"]')).not.toBeNull());
    expect(writes.approved).toEqual([5]);
    expect(writes.replies).toEqual([]);
    expect(host.querySelector('[data-chat-receipt]')).toBeNull();
  });

  test('not now is the reply write', async () => {
    const host = draw(ChatCard, { item: card('trust:4:ab'), card: 'question', agentName: 'Loki' });
    (host.querySelector('[data-decide="no"]') as HTMLButtonElement).click();
    await vi.waitFor(() => expect(host.querySelector('[data-chat-decision="no"]')).not.toBeNull());
    expect(writes.replies).toEqual(['not now']);
    expect(writes.approved).toEqual([]);
  });

  test('a decided card shows its decision and no keys', () => {
    const host = draw(ChatCard, { item: card('trust:4:ab', 'done'), card: 'question', agentName: 'Loki' });
    expect(host.querySelector('[data-chat-receipt]')).toBeNull();
    expect(host.querySelector('[data-chat-decision]')?.textContent).toBe('approved');
  });
});

describe('no session picker in an agent chat', () => {
  test('no reply box has a picker', () => {
    const chat = draw(HuddleReply, { item: card('question:3'), agentName: 'Loki', noSend: true });
    expect(chat.querySelector('[data-huddle-reply-target]')).toBeNull();
    unmount(app as object, { outro: false });
    const lists = draw(HuddleReply, { item: card('question:3') });
    expect(lists.querySelector('[data-huddle-reply-target]')).toBeNull();
  });
});
