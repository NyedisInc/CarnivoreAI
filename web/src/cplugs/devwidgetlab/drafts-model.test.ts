import { describe, expect, it } from 'vitest';
import { codeGap, stateWord, type DraftSummary } from './drafts-model';

const DRAFT = {
  slug: 'pulse-board', kind: 'new', widget: 'core.pulse-board', title: 'Pulse board', created: '', state: 'built', base_sha: 'old', session: null, files: [],
  build: { state: 'built', sha: 'abc', built_at: '', log: null, error: '' }, manifest: null, stale: true, build_stale: false, code: { app: '', build: '', source: '' },
} as DraftSummary;

describe('the code behind a draft', () => {
  it('names the gap between the app and the build, short, only when both are known and differ', () => {
    expect(codeGap({ app: 'dc699b5', build: '9f1e2d3c4b5a', source: '9f1e2d3c4b5a' })).toEqual({ app: 'dc699b5', build: '9f1e2d3' });
    expect(codeGap({ app: 'dc699b5', build: 'dc699b5abbe9', source: 'dc699b5abbe9' })).toBeNull();
    expect(codeGap({ app: '', build: '9f1e2d3', source: '' })).toBeNull();
    expect(codeGap(undefined)).toBeNull();
  });

  it('reads stale for a build that is not the code the Lab reads, not for a draft that merely began on older code', () => {
    expect(stateWord(DRAFT)).toBe('built');
    expect(stateWord({ ...DRAFT, build_stale: true })).toBe('stale');
  });
});
