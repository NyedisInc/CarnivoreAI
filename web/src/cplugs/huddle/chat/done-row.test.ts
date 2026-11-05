/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it } from 'vitest';

import EventCard from './EventCard.svelte';
import { cardLineId, chatRows } from './chat-model';
import type { SwarmEntry } from './chat-api';

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
});

const done = { kind: 'event', id: 'ev:done:card:41', at: 3, event: 'done', ref: 'card:41', text: 'Rook: login remembers the account, done' } as SwarmEntry;
const quiet = (id: string, at: number) => ({ kind: 'event', id, at, event: 'spawned', ref: `agent:${id}`, text: 'Loki spawned Rook' }) as SwarmEntry;

describe('the done row', () => {
  it('names its card and draws in place between quiet events', () => {
    expect(cardLineId(done)).toBe(41);
    const rows = chatRows([quiet('a', 1), quiet('b', 2), done, quiet('c', 4), quiet('d', 5)], { id: 3, name: 'Boss' });
    expect(rows.map((r) => r.kind === 'fold' ? `fold:${r.entries.length}` : r.entry.id)).toEqual(['fold:2', 'ev:done:card:41', 'fold:2']);
  });

  it('shows the done label, the line, and a card icon that opens the card', () => {
    const target = document.createElement('div');
    document.body.appendChild(target);
    handle = mount(EventCard, { target, props: { event: 'done', text: 'Rook: login remembers the account, done', cardId: 41 } });
    flushSync();
    expect(target.querySelector('[data-chat-event="done"] .hde-label')?.textContent).toBe('done');
    expect(target.querySelector('.hde-text')?.textContent).toBe('Rook: login remembers the account, done');
    expect(target.querySelector('button[data-chat-card-open]')?.getAttribute('data-chat-card-open')).toBe('41');
  });
});
