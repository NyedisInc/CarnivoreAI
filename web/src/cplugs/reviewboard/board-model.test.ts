import { describe, expect, it } from 'vitest';
import {
  COLLAPSE_AFTER, defaultFit, fitScale, frameWidth, historyItems, paramsFromSearch, revisionById, stepRevision, visibleHistory,
} from './board-model';
import { boardAnswer, revision, round } from './fixtures';

const sidecar = boardAnswer().sidecar!;

describe('the history bar order', () => {
  it('is time order: a revision, then the rounds sent before the next one', () => {
    expect(historyItems(sidecar).map((i) => i.id)).toEqual(['r1', 'n1', 'r2', 'r3']);
  });

  it('puts a revision before a round that shares its second, and marks an undelivered round', () => {
    const tied = boardAnswer({ rounds: [round(1, 'r1', { sent_at: '2026-10-13T14:01:00Z', delivery: { state: 'undelivered' } })] }).sidecar!;
    const items = historyItems(tied);
    expect(items.map((i) => i.id).slice(0, 2)).toEqual(['r1', 'n1']);
    expect(items[1]!.undelivered).toBe(true);
  });
});

describe('folding the oldest revisions', () => {
  const many = { ...sidecar, revisions: Array.from({ length: 25 }, (_, i) => revision(i + 1, { created_at: `2026-10-13T14:${String(i).padStart(2, '0')}:00Z` })), rounds: [] };

  it('folds all but the newest 20 into one chip', () => {
    const shown = visibleHistory(historyItems(many), 25, false);
    expect(shown.folded).toEqual({ from: 1, to: 25 - COLLAPSE_AFTER });
    expect(shown.items).toHaveLength(COLLAPSE_AFTER);
    expect(shown.items[0]!.id).toBe('r6');
  });

  it('shows everything once opened, and never folds a short board', () => {
    expect(visibleHistory(historyItems(many), 25, true).items).toHaveLength(25);
    expect(visibleHistory(historyItems(sidecar), 3, false).folded).toBeNull();
  });
});

describe('stepping and fitting', () => {
  it('steps one revision and stops at both ends', () => {
    expect(stepRevision(sidecar, 'r2', -1)).toBe('r1');
    expect(stepRevision(sidecar, 'r1', -1)).toBe('r1');
    expect(stepRevision(sidecar, 'r3', 1)).toBe('r3');
    expect(stepRevision(sidecar, 'r9', 1)).toBe('r9');
    expect(revisionById(sidecar, 'r2')?.id).toBe('r2');
    expect(revisionById(sidecar, null)).toBeNull();
  });

  it('shows the real width when it fits and scales down when it does not', () => {
    expect(defaultFit(300, 412)).toBe('actual');
    expect(defaultFit(1400, 412)).toBe('fit');
    expect(defaultFit(1400, 0)).toBe('actual');
    expect(fitScale(1400, 700)).toBe(0.5);
    expect(fitScale(300, 700)).toBe(1);
    expect(fitScale(2560, 10)).toBe(0.1);
  });
});

describe('the pop-out address', () => {
  it('reads a board and a revision, and refuses anything malformed', () => {
    expect(paramsFromSearch('?tab=reviewboard&board=20261013-bottom-bar&rev=r2')).toEqual({ board: '20261013-bottom-bar', rev: 'r2' });
    expect(paramsFromSearch('?tab=reviewboard')).toEqual({ board: null, rev: null });
    expect(paramsFromSearch('?board=../etc&rev=2')).toEqual({ board: null, rev: null });
  });
});

describe('frameWidth', () => {
  it('fills the room but never goes under the declared viewport', () => {
    expect(frameWidth(520, 1100, 1)).toBe(1100);
    expect(frameWidth(520, 300, 1)).toBe(520);
  });
  it('keeps the viewport width when scaled down to fit, so fill and fit do not fight', () => expect(frameWidth(1400, 700, 0.5)).toBe(1400));
});
