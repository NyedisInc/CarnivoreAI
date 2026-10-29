import { describe, expect, it } from 'vitest';
import { codeGap, compareDelta, reportKey, stateWord, type DraftSummary } from './drafts-model';

const DRAFT = {
  slug: 'pulse-board', kind: 'new', widget: 'core.pulse-board', title: 'Pulse board', created: '', state: 'built', base_sha: 'old', session: null, files: [],
  build: { state: 'built', sha: 'abc', built_at: '', log: null, error: '' }, manifest: null, stale: true, build_stale: false, code: { app: '', build: '', source: '' },
} as DraftSummary;

describe('the code behind a draft', () => {
  it('names the gap between the app and the build, short, only when both are known and differ', () => {
    expect(codeGap({ app: 'dbea280', build: '9f1e2d3c4b5a', source: '9f1e2d3c4b5a' })).toEqual({ app: 'dbea280', build: '9f1e2d3' });
    expect(codeGap({ app: 'dbea280', build: 'dbea28019d25', source: 'dbea28019d25' })).toBeNull();
    expect(codeGap({ app: '', build: '9f1e2d3', source: '' })).toBeNull();
    expect(codeGap(undefined)).toBeNull();
  });

  it('reads stale for a build that is not the code the Lab reads, not for a draft that merely began on older code', () => {
    expect(stateWord(DRAFT)).toBe('built');
    expect(stateWord({ ...DRAFT, build_stale: true })).toBe('stale');
  });
});

describe('the compare strip across drawers (u123-01)', () => {
  it('keeps one count per dock, so two docks of one host both have to report', () => {
    const counts: Record<string, number> = {
      [reportKey('drawer', 'left', 'wide', 'current')]: 0, [reportKey('drawer', 'left', 'wide', 'draft')]: 0,
    };
    expect(compareDelta(counts, 2, true).kind).toBe('waiting');
    counts[reportKey('drawer', 'right', 'wide', 'current')] = 0;
    counts[reportKey('drawer', 'right', 'wide', 'draft')] = 2;
    expect(compareDelta(counts, 2, true)).toEqual({ kind: 'more', current: 0, draft: 2 });
  });
});
