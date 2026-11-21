import { describe, expect, it } from 'vitest';
import type { BoardPrompt } from './board-model';
import { GAP_MARGIN, estimateRooms, groupByAnchor, inlinePrompts, placeBlocks, roomsFromHeights, sameRooms } from './inline-picks-model';

const prompts: BoardPrompt[] = [
  { id: 'a', kind: 'choice', label: 'a', anchor: 'send', options: [{ id: 'x', label: 'x' }] },
  { id: 'b', kind: 'check', label: 'b', anchor: 'send' },
  { id: 'c', kind: 'question', label: 'c', anchor: 'footer' },
  { id: 'd', kind: 'check', label: 'd' },
  { id: 'e', kind: 'check', label: 'e', anchor: 'undeclared' },
];
const revision = { inline_picks: true, anchors: [{ id: 'send', label: 's' }, { id: 'footer', label: 'f' }], prompts };

describe('which prompts are drawn inline', () => {
  it('takes the prompts that name a declared anchor, when the board asks for it and the newest revision is shown', () => {
    expect(inlinePrompts(revision, true).map((p) => p.id)).toEqual(['a', 'b', 'c']);
  });

  it('draws none when the board did not ask, the reader is on an older revision, or nothing is shown', () => {
    expect(inlinePrompts({ ...revision, inline_picks: null }, true)).toEqual([]);
    expect(inlinePrompts(revision, false)).toEqual([]);
    expect(inlinePrompts(null, true)).toEqual([]);
  });

  it('groups the prompts by anchor in first-seen order', () => {
    expect(groupByAnchor(prompts).map(([anchor, group]) => [anchor, group.map((p) => p.id)])).toEqual([['send', ['a', 'b']], ['footer', ['c']], ['undeclared', ['e']]]);
  });
});

describe('the room asked of the frame', () => {
  it('starts from a guess per kind, summed per anchor with the margin', () => {
    expect(estimateRooms(prompts.slice(0, 3))).toEqual({ send: 64 + 40 + GAP_MARGIN, footer: 80 + GAP_MARGIN });
  });

  it('takes a measured height back into the frame pixels at the fit scale, rounded up', () => {
    expect(roomsFromHeights({ send: 90 }, 0.5)).toEqual({ send: 180 + GAP_MARGIN });
    expect(roomsFromHeights({ send: 91 }, 1)).toEqual({ send: 91 + GAP_MARGIN });
    expect(roomsFromHeights({ send: 0, bad: Number.NaN }, 1)).toEqual({});
  });

  it('tells whether two asks are the same so the frame is not asked twice', () => {
    expect(sameRooms({ a: 1 }, { a: 1 })).toBe(true);
    expect(sameRooms({ a: 1 }, { a: 2 })).toBe(false);
    expect(sameRooms({ a: 1 }, { a: 1, b: 2 })).toBe(false);
  });
});

describe('where the blocks sit', () => {
  it('places a block at its gap spot scaled to the screen, and leaves an anchor the page has not placed to the tray', () => {
    const placed = placeBlocks(prompts.slice(0, 3), { send: { x: 10, y: 200, w: 400 } }, 0.5);
    expect(placed).toHaveLength(1);
    expect(placed[0]).toMatchObject({ anchor: 'send', left: 5, top: 100, width: 200 });
    expect(placed[0]!.prompts.map((p) => p.id)).toEqual(['a', 'b']);
  });
});
