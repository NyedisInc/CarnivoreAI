/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync } from 'svelte';
import { mountCardLayer } from './overlay';
import { cardSettings } from './prefs.svelte';
import { clearKept, followKept } from './keep.svelte';
import { CARD_TTL_MS, MAX_KEPT_CARDS, type CardFrame } from './model';

type Handler = (frame: { type?: string }) => void;
let handlers: Handler[] = [];
let termReads = 0;
const stops: Array<() => void> = [];

const frame = (over: Partial<CardFrame> = {}): CardFrame => ({
  type: 'crosstalk.card', id: 'm-1', thread: 't-1', sender_id: 'ses_a', sender_uuid: null, sender_name: 'Alpha', sender_provider: 'claude',
  sender_model: 'opus', receiver_id: 'ses_b', receiver_uuid: null, receiver_name: 'Beta', receiver_provider: 'codex', receiver_model: null,
  preview: 'ping the build', at: 1_700_000_000, ...over,
});

function cell(sessionId: string): HTMLElement {
  const host = document.createElement('div');
  document.body.append(host);
  const controller = { _sessionId: () => sessionId, get term(): never { termReads += 1; throw new Error('xterm was read'); } };
  stops.push(mountCardLayer({ slot: 'terminal:x', controller: controller as never, host }));
  flushSync();
  return host;
}

function push(f: CardFrame): void {
  for (const handler of handlers) handler(f);
  flushSync();
}

beforeEach(() => {
  handlers = [];
  termReads = 0;
  cardSettings.enabled = true;
  cardSettings.senderCards = true;
  cardSettings.receiverCards = true;
  cardSettings.keepCards = false;
  clearKept();
  (globalThis as { AppEvents?: unknown }).AppEvents = { subscribe: (h: Handler) => { handlers.push(h); return () => { handlers = handlers.filter((x) => x !== h); }; } };
});
afterEach(() => {
  for (const stop of stops.splice(0)) stop();
  document.body.innerHTML = '';
  vi.useRealTimers();
  delete (globalThis as { AppEvents?: unknown }).AppEvents;
});

test('a frame draws FROM on the receiver and TO on the sender, and reads no terminal buffer', () => {
  vi.useFakeTimers();
  const listen = vi.spyOn(window, 'addEventListener');
  const receiver = cell('ses_b');
  const sender = cell('ses_a');
  const bystander = cell('ses_c');
  expect(vi.getTimerCount()).toBe(0);
  push(frame());
  expect(receiver.querySelector('[data-side="received"]')?.textContent).toContain('ping the build');
  expect(receiver.querySelector('.xtalk-card__name')?.textContent).toBe('@Alpha');
  expect(sender.querySelector('[data-side="sent"] .xtalk-card__name')?.textContent).toBe('@Beta');
  expect(bystander.querySelector('.xtalk-card')).toBeNull();
  expect(termReads).toBe(0);
  expect(listen.mock.calls.some(([type]) => type === 'terminal-created')).toBe(false);
  listen.mockRestore();
});

test('one card per message even when the frame repeats', () => {
  const receiver = cell('ses_b');
  push(frame());
  push(frame());
  expect(receiver.querySelectorAll('.xtalk-card')).toHaveLength(1);
});

test('a click dismisses the card', () => {
  const receiver = cell('ses_b');
  push(frame());
  receiver.querySelector<HTMLButtonElement>('.xtalk-card')?.click();
  flushSync();
  expect(receiver.querySelector('.xtalk-card')).toBeNull();
});

test('a card expires on its own and leaves no timer behind', () => {
  vi.useFakeTimers();
  const receiver = cell('ses_b');
  push(frame());
  expect(receiver.querySelector('.xtalk-card')).not.toBeNull();
  vi.advanceTimersByTime(CARD_TTL_MS + 1);
  flushSync();
  expect(receiver.querySelector('.xtalk-card')).toBeNull();
  expect(vi.getTimerCount()).toBe(0);
});

test('each side has its own switch', () => {
  cardSettings.senderCards = false;
  const receiver = cell('ses_b');
  const sender = cell('ses_a');
  push(frame());
  expect(receiver.querySelector('.xtalk-card')).not.toBeNull();
  expect(sender.querySelector('.xtalk-card')).toBeNull();
});

test('disposing the layer drops its subscription', () => {
  cell('ses_b');
  expect(handlers).toHaveLength(1);
  for (const stop of stops.splice(0)) stop();
  flushSync();
  expect(handlers).toHaveLength(0);
});

test('keepCards on: a card survives the timer and a tab switch, in order, and a dismiss removes it', () => {
  vi.useFakeTimers();
  cardSettings.keepCards = true;
  stops.push(followKept());
  let receiver = cell('ses_b');
  const leave = stops.pop() as () => void;
  push(frame({ id: 'm-1', preview: 'first' }));
  push(frame({ id: 'm-2', preview: 'second' }));
  expect(vi.getTimerCount()).toBe(0);
  vi.advanceTimersByTime(CARD_TTL_MS * 5);
  flushSync();
  expect(receiver.querySelectorAll('.xtalk-card')).toHaveLength(2);
  leave();
  push(frame({ id: 'm-3', preview: 'third' }));
  receiver = cell('ses_b');
  const previews = [...receiver.querySelectorAll('.xtalk-card__quote')].map((el) => el.textContent);
  expect(previews).toEqual(['first', 'second', 'third']);
  receiver.querySelector<HTMLButtonElement>('[data-message-id="m-2"]')?.click();
  flushSync();
  expect([...receiver.querySelectorAll('.xtalk-card__quote')].map((el) => el.textContent)).toEqual(['first', 'third']);
  expect(cell('ses_c').querySelector('.xtalk-card')).toBeNull();
});

test('keepCards on: the kept stack per session is capped and the oldest drops', () => {
  cardSettings.keepCards = true;
  stops.push(followKept());
  const receiver = cell('ses_b');
  for (let i = 0; i < MAX_KEPT_CARDS + 3; i += 1) push(frame({ id: `m-${i}`, preview: `p${i}` }));
  const previews = [...receiver.querySelectorAll('.xtalk-card__quote')].map((el) => el.textContent);
  expect(previews).toHaveLength(MAX_KEPT_CARDS);
  expect(previews[0]).toBe('p3');
});

test('keepCards off: the card times out as before', () => {
  vi.useFakeTimers();
  stops.push(followKept());
  const receiver = cell('ses_b');
  push(frame());
  vi.advanceTimersByTime(CARD_TTL_MS + 1);
  flushSync();
  expect(receiver.querySelector('.xtalk-card')).toBeNull();
});

test('with the master preference off no card is drawn and none is kept', () => {
  cardSettings.enabled = false;
  const receiver = cell('ses_b');
  push(frame());
  expect(receiver.querySelector('.xtalk-card')).toBeNull();
  cardSettings.keepCards = true;
  followKept();
  push(frame({ id: 'm-2' }));
  cardSettings.enabled = true;
  flushSync();
  expect(receiver.querySelector('.xtalk-card')).toBeNull();
});
