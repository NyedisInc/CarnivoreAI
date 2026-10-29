import { describe, expect, it } from 'vitest';
import type { CrosstalkThread, ThreadParticipant } from '../../../lib/crosstalk/history/history-model';
import {
  ageText, countText, delivery, direction, emptyText, isNew, isSeenMarks, markAllSeen, markSeen, MAX_MARKS, NO_MARKS,
  clampSplit, isSplit, layoutFor, loadingText, scopeCaption, splitStep, STACK_MIN_HEIGHT, stepIndex, transcript, type ThreadMessage,
} from './model';

const NOW_MS = Date.UTC(2026, 8, 30, 15, 0, 0);
const NOW = NOW_MS / 1000;

function side(key: string, name: string): ThreadParticipant {
  return { key, id: key, session_uuid: null, name, provider: 'claude', model: 'opus', project_id: 1, project_name: 'p' };
}
const A = side('ses_a', 'alpha');
const B = side('ses_b', 'beta');

function thread(over: Partial<CrosstalkThread> = {}): CrosstalkThread {
  return { thread: 't1', participants: [A, B], message_count: 2, last_at: NOW - 60, first_at: NOW - 600, last_preview: 'hi',
    last_sender_key: 'ses_b', last_status: 'delivered', ...over };
}

function msg(id: string, from: ThreadParticipant, to: ThreadParticipant, agoS: number, over: Partial<ThreadMessage> = {}): ThreadMessage {
  return { id, source: 'crosstalk', thread: 't1', sender_key: from.key, receiver_key: to.key, sender_id: from.id, sender_uuid: null,
    sender_name: from.name, receiver_id: to.id, receiver_uuid: null, receiver_name: to.name, text: `text ${id}`, status: 'delivered',
    created_at: NOW - agoS, ...over };
}

describe('direction', () => {
  it('names the last speaker first', () => {
    expect(direction(thread()).from.name).toBe('beta');
    expect(direction(thread({ last_sender_key: 'ses_a' })).from.name).toBe('alpha');
  });
  it('falls back to the first side when the last speaker is not a participant', () => {
    expect(direction(thread({ last_sender_key: 'nobody' })).from.name).toBe('alpha');
  });
});

describe('new and read marks', () => {
  const baseline = NOW - 3600;
  it('with no marks, activity inside the window is new and older activity is not', () => {
    expect(isNew(thread({ last_at: NOW - 60 }), NO_MARKS, baseline)).toBe(true);
    expect(isNew(thread({ last_at: NOW - 7200 }), NO_MARKS, baseline)).toBe(false);
  });
  it('a conversation read up to its last activity is not new until it moves again', () => {
    const marks = markSeen(NO_MARKS, 't1', NOW - 60, baseline);
    expect(isNew(thread({ last_at: NOW - 60 }), marks, baseline)).toBe(false);
    expect(isNew(thread({ last_at: NOW - 30 }), marks, baseline)).toBe(true);
    expect(marks.since).toBe(baseline);
  });
  it('mark all read covers every conversation up to now', () => {
    expect(isNew(thread(), markAllSeen(NOW), baseline)).toBe(false);
  });
  it('keeps at most MAX_MARKS marks, dropping the oldest', () => {
    let marks = NO_MARKS;
    for (let i = 0; i < MAX_MARKS + 5; i += 1) marks = markSeen(marks, `t${i}`, i, baseline);
    expect(Object.keys(marks.threads)).toHaveLength(MAX_MARKS);
    expect(marks.threads['t0']).toBeUndefined();
  });
  it('refuses a malformed stored value', () => {
    expect(isSeenMarks({ since: 0, threads: {} })).toBe(true);
    expect(isSeenMarks({ since: '0', threads: {} })).toBe(false);
    expect(isSeenMarks({ since: 0, threads: { t: 'x' } })).toBe(false);
    expect(isSeenMarks(null)).toBe(false);
  });
});

describe('words', () => {
  it('ages are short', () => {
    expect(ageText(NOW - 20, NOW_MS)).toBe('now');
    expect(ageText(NOW - 480, NOW_MS)).toBe('8m');
    expect(ageText(NOW - 3 * 3600, NOW_MS)).toBe('3h');
    expect(ageText(NOW - 2 * 86400, NOW_MS)).toBe('2d');
  });
  it('a delivered message says nothing; trouble says what happened', () => {
    expect(delivery('delivered', 'beta')).toBeNull();
    expect(delivery('held', 'beta')).toEqual({ word: 'waiting for beta', bad: false });
    expect(delivery('failed', 'beta')?.bad).toBe(true);
    expect(delivery('expired', 'beta')?.bad).toBe(true);
  });
  it('the caption names the scope and its subject', () => {
    expect(scopeCaption('project', 'billing-api')).toEqual({ label: 'this project', subject: 'billing-api' });
    expect(scopeCaption('all', 'billing-api')).toEqual({ label: 'all conversations', subject: '' });
    expect(countText(3, 1, false)).toBe('3 conversations, 1 new');
    expect(countText(1, 0, false)).toBe('1 conversation');
    expect(countText(50, 0, true)).toBe('50+ conversations');
    expect(countText(5, 2, false, true)).toBe('2 new');
    expect(countText(5, 0, true, true)).toBe('5+');
  });
  it('the loading sentence names what is read', () => {
    expect(loadingText('project', 'billing-api')).toBe("reading the billing-api project's conversations...");
    expect(loadingText('all', '')).toBe('reading all conversations...');
  });
  it('an empty list says where nothing was found', () => {
    expect(emptyText('project', 'billing-api')).toContain('billing-api');
    expect(emptyText('session', 'docs-site')).toContain('docs-site');
  });
});

describe('transcript', () => {
  it('breaks days, folds a run, links a reply that is not right above, and keeps an open ask', () => {
    const items = transcript([
      msg('m1', A, B, 2 * 86400, { expect_reply: 1 }),
      msg('m2', B, A, 600, { in_reply_to: 'm1' }),
      msg('m3', B, A, 560),
      msg('m4', A, B, 300, { in_reply_to: 'm2', expect_reply: 1 }),
    ], [A, B], NOW_MS);
    expect(items.map((item) => item.kind)).toEqual(['day', 'message', 'day', 'message', 'message', 'message']);
    const messages = items.filter((item) => item.kind === 'message');
    expect(messages.map((m) => m.head)).toEqual([true, true, false, true]);
    expect(messages.map((m) => m.side)).toEqual([0, 1, 1, 0]);
    expect(messages[1]!.replyTo).toBe('text m1');
    expect(messages[3]!.replyTo).toBe('text m2');
    expect(messages[0]!.asksReply).toBe(false);
    expect(messages[3]!.asksReply).toBe(true);
  });
  it('a reply to the message right above needs no link', () => {
    const items = transcript([msg('m1', A, B, 600), msg('m2', B, A, 500, { in_reply_to: 'm1' })], [A, B], NOW_MS);
    expect(items.filter((item) => item.kind === 'message').map((m) => m.replyTo)).toEqual(['', '']);
  });
  it('a server notice is a notice, never a message, and breaks a run', () => {
    const items = transcript([
      msg('m1', A, B, 600), msg('n1', A, A, 590, { source: 'system' }), msg('m2', A, B, 580),
    ], [A, B], NOW_MS);
    expect(items.map((item) => item.kind)).toEqual(['day', 'message', 'notice', 'message']);
    expect(items[3]!.kind === 'message' && items[3]!.head).toBe(true);
  });
});

describe('list keys', () => {
  it('moves and clamps', () => {
    expect(stepIndex('ArrowDown', 0, 5, 3)).toBe(1);
    expect(stepIndex('ArrowUp', 0, 5, 3)).toBe(0);
    expect(stepIndex('End', 0, 5, 3)).toBe(4);
    expect(stepIndex('PageDown', 3, 5, 3)).toBe(4);
    expect(stepIndex('x', 0, 5, 3)).toBeNull();
    expect(stepIndex('ArrowDown', 0, 0, 3)).toBeNull();
  });
});

describe('layout and the stacked divider', () => {
  it('side by side from 560 wide, stacked when narrow and tall, one at a time when narrow and short', () => {
    expect(layoutFor(760, 440)).toBe('side');
    expect(layoutFor(380, 780)).toBe('stack');
    expect(layoutFor(320, 480)).toBe('stack');
    expect(layoutFor(300, 200)).toBe('drill');
  });
  it('stacks in a right bar shared by two widgets', () => {
    expect(STACK_MIN_HEIGHT).toBe(320);
    expect(layoutFor(380, 420)).toBe('stack');
    expect(layoutFor(380, 320)).toBe('stack');
    expect(layoutFor(380, 319)).toBe('drill');
  });
  it('the divider stays in range and its keys step, jump and reset', () => {
    expect(clampSplit(0.9)).toBe(0.75);
    expect(clampSplit(0.05)).toBe(0.2);
    expect(splitStep('ArrowDown', 0.4)).toBe(0.45);
    expect(splitStep('ArrowUp', 0.2)).toBe(0.2);
    expect(splitStep('Enter', 0.7)).toBe(0.4);
    expect(splitStep('x', 0.4)).toBeNull();
    expect(isSplit(0.4)).toBe(true);
    expect(isSplit(0.9)).toBe(false);
    expect(isSplit('0.4')).toBe(false);
  });
});
