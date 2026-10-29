import { expect, test } from 'vitest';
import { MAX_CARDS, cardOf, sideEnabled, sideOf, withCard, type CardFrame } from './model';

const frame = (over: Partial<CardFrame> = {}): CardFrame => ({
  id: 'm-1', thread: 't-1', sender_id: 'ses_a', sender_uuid: 'uuid-a', sender_name: 'Alpha', sender_provider: 'claude', sender_model: 'opus',
  receiver_id: 'ses_b', receiver_uuid: 'uuid-b', receiver_name: 'Beta', receiver_provider: 'codex', receiver_model: 'gpt', preview: 'ping', at: 1, ...over,
});

test('the receiving terminal is FROM and the sending terminal is TO, by id or uuid; anyone else gets nothing', () => {
  expect(sideOf(frame(), 'ses_b')).toBe('received');
  expect(sideOf(frame(), 'uuid-b')).toBe('received');
  expect(sideOf(frame(), 'ses_a')).toBe('sent');
  expect(sideOf(frame(), 'ses_other')).toBeNull();
  expect(sideOf(frame(), null)).toBeNull();
});

test('each side reads its own peer: FROM names the sender, TO names the receiver', () => {
  expect(cardOf(frame(), 'received')).toMatchObject({ peer: 'Alpha', provider: 'claude', model: 'opus', preview: 'ping' });
  expect(cardOf(frame(), 'sent')).toMatchObject({ peer: 'Beta', provider: 'codex', model: 'gpt' });
  expect(cardOf(frame({ receiver_name: null }), 'sent').peer).toBe('ses_b');
});

test('a side is on unless its switch is false', () => {
  expect(sideEnabled({ senderCards: false, receiverCards: true, keepCards: false }, 'sent')).toBe(false);
  expect(sideEnabled({ senderCards: false, receiverCards: true, keepCards: false }, 'received')).toBe(true);
  expect(sideEnabled({ senderCards: true, receiverCards: false, keepCards: false }, 'received')).toBe(false);
});

test('one card per message and the list is capped', () => {
  let cards = withCard([], cardOf(frame(), 'received'));
  expect(withCard(cards, cardOf(frame(), 'received'))).toHaveLength(1);
  for (let i = 0; i < MAX_CARDS + 2; i += 1) cards = withCard(cards, cardOf(frame({ id: `m-${i + 10}` }), 'received'));
  expect(cards).toHaveLength(MAX_CARDS);
  expect(cards[cards.length - 1]?.id).toBe(`m-${MAX_CARDS + 11}`);
});
