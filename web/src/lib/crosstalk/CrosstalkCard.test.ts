/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const listing = vi.hoisted(() => ({ data: [] as Array<{ session: { id: string }; tmux_session: string | null }> }));
const navigate = vi.hoisted(() => vi.fn());
vi.mock('../../opscenter/api/sessions.svelte', () => ({ sessions: listing }));
vi.mock('../../opscenter/api/host', () => ({ openSession: navigate }));

import CrosstalkCard from './CrosstalkCard.svelte';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  for (const item of mounted) unmount(item, { outro: false });
  mounted.length = 0;
  document.body.innerHTML = '';
  listing.data = [];
  navigate.mockClear();
  window.getSelection()?.removeAllRanges();
});

function card(senderId = 'ses_sender'): HTMLElement {
  const host = document.createElement('div');
  document.body.append(host);
  mounted.push(mount(CrosstalkCard, { target: host, props: {
    sessionId: 'ses_receiver', message: {
      id: 'm-longparagraph', source: 'crosstalk', thread: 't-one',
      sender_id: senderId, sender_uuid: null, sender_name: 'bot-Website',
      sender_provider: 'claude', sender_model: 'sonnet', receiver_id: 'ses_receiver',
      receiver_uuid: null, text: 'one long paragraph '.repeat(40), status: 'delivered', created_at: 1,
    },
  } }));
  flushSync();
  return host.querySelector('.crosstalk-card')!;
}

test('wrapped text expands by card or keyboard control; exact live sender navigates without toggling', () => {
  listing.data = [{ session: { id: 'ses_sender' }, tmux_session: 'cloude_sender' }];
  const article = card();
  const quote = article.querySelector<HTMLElement>('.crosstalk-card__quote')!;
  const toggle = article.querySelector<HTMLButtonElement>('.crosstalk-card__toggle')!;
  const sender = article.querySelector<HTMLButtonElement>('.crosstalk-card__sender')!;

  expect(toggle.getAttribute('aria-expanded')).toBe('false');
  quote.click();
  flushSync();
  expect(quote.classList.contains('crosstalk-card__quote--expanded')).toBe(true);
  expect(toggle.getAttribute('aria-expanded')).toBe('true');

  sender.click();
  flushSync();
  expect(navigate).toHaveBeenCalledWith('ses_sender', 'cloude_sender');
  expect(toggle.getAttribute('aria-expanded')).toBe('true');

  toggle.focus();
  toggle.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  toggle.click();
  flushSync();
  expect(toggle.getAttribute('aria-expanded')).toBe('false');

  const range = document.createRange();
  range.setStart(quote.firstChild!, 0);
  range.setEnd(quote.firstChild!, 3);
  window.getSelection()?.removeAllRanges();
  window.getSelection()?.addRange(range);
  expect(window.getSelection()?.toString()).toBe('one');
  quote.click();
  flushSync();
  expect(toggle.getAttribute('aria-expanded')).toBe('false');

  const missing = card('ses_closed');
  expect(missing.querySelector('.crosstalk-card__sender')).toBe(null);
  expect(missing.querySelector('.crosstalk-card__name')?.textContent).toBe('@bot-Website');
});
