import { describe, expect, test } from 'vitest';
import { confirmKey, roundText } from './round-confirm';

describe('the confirm line after a board Send', () => {
  test('posted and telling, posted, undelivered and kept each have their own words', () => {
    const base = { title: 't', item: 1 };
    expect(confirmKey({ ...base, delivered: true, telling: true })).toBe('cplug.reviewboard.tray.posted_telling');
    expect(confirmKey({ ...base, delivered: true })).toBe('cplug.reviewboard.tray.posted');
    expect(confirmKey({ ...base, delivered: false })).toBe('cplug.reviewboard.tray.not_delivered_to');
    expect(confirmKey({ ...base, delivered: false, kept: true })).toBe('cplug.reviewboard.tray.kept');
  });

  test('a round copy holds the note, the answers and the anchor notes', () => {
    const text = roundText({
      client_round_id: 'c', revision: 'r1', note: 'tighten the header', context: {},
      answers: [{ prompt: 'p1', options: ['a', 'b'], note: 'because' }], anchor_notes: [{ anchor: 'hdr', text: 'too tall' }],
    });
    expect(text).toContain('tighten the header');
    expect(text).toContain('p1: a, b / because');
    expect(text).toContain('hdr: too tall');
  });
});
