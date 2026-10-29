/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';

const reads: string[] = [];
let answer: () => Promise<unknown> = async () => ({ id: 41, archived_at: null });
vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return { ...real, authFetch: vi.fn(async (path: string) => { reads.push(path); return answer(); }) };
});
const opened = vi.fn();
vi.mock('../../../lib/huddle-swarm/screen-host', () => ({ openHuddleSwarmScreen: () => opened() }));

import { ApiError } from '../../../opscenter/api/auth.svelte';
import { boardFocus } from '../../../lib/swarm-board/board-focus.svelte';
import EventCard from './EventCard.svelte';
import { cardLineId } from './chat-model';

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  reads.length = 0;
  opened.mockClear();
  boardFocus.request = null;
  document.body.innerHTML = '';
});
const settle = () => new Promise((r) => setTimeout(r, 0));

function draw(cardId: number | null): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  handle = mount(EventCard, { target, props: { event: 'card', text: 'Loki made card x', cardId } });
  flushSync();
  return target;
}

describe('the chat card line icon', () => {
  it('reads the card id off a card line ref only', () => {
    expect(cardLineId({ kind: 'event', event: 'card', ref: 'card:41' })).toBe(41);
    expect(cardLineId({ kind: 'event', event: 'card', ref: '' })).toBeNull();
    expect(cardLineId({ kind: 'event', event: 'reported', ref: 'card:41' })).toBeNull();
  });

  it('a click routes to the board with that card id', async () => {
    const button = draw(41).querySelector('button[data-chat-card-open]') as HTMLButtonElement;
    expect(button.getAttribute('data-chat-card-open')).toBe('41');
    button.click();
    await settle();
    expect(reads).toEqual(['/swarm/cards/41']);
    expect(boardFocus.request).toMatchObject({ id: 41, archived: false });
    expect(opened).toHaveBeenCalledOnce();
  });

  it('a card that is gone opens nothing; a line with no card draws no icon', async () => {
    answer = async () => { throw new ApiError('not a card', 404, 'not_a_card'); };
    (draw(7).querySelector('button[data-chat-card-open]') as HTMLButtonElement).click();
    await settle();
    expect(boardFocus.request).toBeNull();
    expect(opened).not.toHaveBeenCalled();
    unmount(handle!);
    handle = null;
    expect(draw(null).querySelector('button[data-chat-card-open]')).toBeNull();
  });
});
