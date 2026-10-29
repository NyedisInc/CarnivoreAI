import { describe, expect, test } from 'vitest';
import type { SwarmEntry } from './chat-api';
import { awaitingReply, composerCap } from './chat-model';

const at = 1;
const owner = { kind: 'owner', id: 'msg:1', at, text: 'do it' } as SwarmEntry;
const agent = { kind: 'agent', id: 'msg:2', at, text: 'done' } as SwarmEntry;
const card = { kind: 'card', id: 'card:3', at } as unknown as SwarmEntry;
const traffic = { kind: 'traffic', id: 'x:4', at, direction: 'out', peer: 'Docs' } as unknown as SwarmEntry;
const event = { kind: 'event', id: 'ev:5', at, event: 'woke' } as unknown as SwarmEntry;

describe('the thinking character shows while the owner waits on the reply (card 1484)', () => {
  test('the owner sent last: waiting, through crosstalk and quiet events', () => {
    expect(awaitingReply([agent, owner])).toBe(true);
    expect(awaitingReply([agent, owner, traffic, event])).toBe(true);
  });

  test('the agent answered, by a post or a card: not waiting', () => {
    expect(awaitingReply([owner, agent])).toBe(false);
    expect(awaitingReply([owner, traffic, card])).toBe(false);
  });

  test('nothing sent yet: not waiting', () => {
    expect(awaitingReply([])).toBe(false);
    expect(awaitingReply([agent, event])).toBe(false);
  });

  test('the box grows to ten lines or 40% of the chat, whichever is smaller, never under two lines', () => {
    expect(composerCap(20, 16, 1000)).toBe(216);
    expect(composerCap(20, 16, 300)).toBe(120);
    expect(composerCap(20, 16, 50)).toBe(56);
  });
});
