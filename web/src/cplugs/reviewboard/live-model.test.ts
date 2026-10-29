import { describe, expect, it } from 'vitest';
import { historyItems, stepRevision, visibleHistory } from './board-model';
import { boardAnswer } from './fixtures';
import { LIVE_ID, isLiveDraft, withLiveDraft } from './live-model';

const live = {
  started_at: '2026-10-16T09:00:00Z', by: { actor: 'claude', session: 'ses_1' }, sends: [], sends_total: 0,
  draft: { seq: 7, updated_at: '2026-10-16T09:05:00Z', summary: 'second look', viewport: 320, views: [{ id: 'main', label: 'main', file: 'draft.html' }],
           prompts: [{ id: 'p', kind: 'check' as const, label: 'ok?', anchor: 'send' }], anchors: [{ id: 'send', label: 'send' }], inline_picks: true },
};

describe('the live draft stands in as the newest revision', () => {
  it('appends a revision named draft, numbered after the last real one, carrying the overwrite count', () => {
    const base = boardAnswer({ live }).sidecar!;
    const shown = withLiveDraft(base)!;
    const stand = shown.revisions.at(-1)!;
    expect(shown.revisions).toHaveLength(base.revisions.length + 1);
    expect(stand).toMatchObject({ id: LIVE_ID, n: 4, summary: 'second look', viewport: 320, stamp: '7', inline_picks: true, answers_round: null });
    expect(stand.prompts[0]!.id).toBe('p');
    expect(base.revisions).toHaveLength(3);
  });

  it('hands a board that is not live back as it is', () => {
    const base = boardAnswer().sidecar!;
    expect(withLiveDraft(base)).toBe(base);
    expect(withLiveDraft(null)).toBeNull();
  });

  it('is found by its id and is the last mark on the history bar, never folded away', () => {
    expect(isLiveDraft(LIVE_ID)).toBe(true);
    expect(isLiveDraft({ id: 'r3' })).toBe(false);
    const shown = withLiveDraft(boardAnswer({ live }).sidecar!)!;
    const items = historyItems(shown);
    expect(items.at(-1)).toMatchObject({ kind: 'revision', id: 'draft' });
    expect(visibleHistory(items, 40, false).items.map((i) => i.id)).toContain('draft');
    expect(stepRevision(shown, 'r3', 1)).toBe('draft');
  });

  it('carries a milestone name onto its history mark', () => {
    const base = boardAnswer().sidecar!;
    base.revisions[1]!.milestone = 'icons only';
    expect(historyItems(base).find((i) => i.id === 'r2')!.milestone).toBe('icons only');
  });
});
