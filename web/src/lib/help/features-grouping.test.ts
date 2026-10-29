import { describe, expect, it } from 'vitest';
import { groupFeaturesByRelease, versionKey, type ReleaseSource } from './features-grouping';

function payload(overrides: Partial<ReleaseSource> = {}): ReleaseSource {
  return {
    catalog: [
      { id: 'help-panel', name: 'Help panel' },
      { id: 'ledger', name: 'Provider ledger' },
    ],
    changes: [],
    ...overrides,
  };
}

describe('versionKey', () => {
  it('reads every digit run as a number, in order', () => {
    expect(versionKey('v1.11.1')).toEqual([1, 11, 1]);
  });

  it('sorts a nameless tag lowest', () => {
    expect(versionKey('nope')).toEqual([0]);
  });
});

describe('groupFeaturesByRelease', () => {
  it('hides internal entries entirely', () => {
    const releases = groupFeaturesByRelease(
      payload({
        changes: [
          { date: '2026-09-20', type: 'internal', features: [], summary: 'refactor', release: 'v1.7.0' },
        ],
      }),
    );
    expect(releases).toEqual([]);
  });

  it('puts Unreleased first and orders tagged releases newest to oldest', () => {
    const releases = groupFeaturesByRelease(
      payload({
        changes: [
          { date: '2026-09-01', type: 'fixed', features: [], summary: 'old fix', release: 'v1.7.0' },
          { date: '2026-09-10', type: 'fixed', features: [], summary: 'new fix', release: 'v1.11.1' },
          { date: '2026-09-26', type: 'added', features: [], summary: 'brand new', release: 'Unreleased' },
        ],
      }),
    );
    expect(releases.map((r) => r.name)).toEqual(['Unreleased', 'v1.11.1', 'v1.7.0']);
    expect(releases[0]?.isUnreleased).toBe(true);
  });

  it('groups by type in Keep-a-Changelog order within a release', () => {
    const releases = groupFeaturesByRelease(
      payload({
        changes: [
          { date: '2026-09-01', type: 'fixed', features: [], summary: 'a fix', release: 'v1.0.0' },
          { date: '2026-09-02', type: 'added', features: [], summary: 'a feature', release: 'v1.0.0' },
          { date: '2026-09-03', type: 'security', features: [], summary: 'a patch', release: 'v1.0.0' },
        ],
      }),
    );
    expect(releases[0]?.types.map((t) => t.type)).toEqual(['added', 'fixed', 'security']);
  });

  it('resolves feature ids to catalog names and carries the PR number', () => {
    const releases = groupFeaturesByRelease(
      payload({
        changes: [
          {
            date: '2026-09-26', type: 'added', features: ['help-panel', 'no-such-id'],
            summary: 'add the releases view', pr: 845, release: 'Unreleased',
          },
        ],
      }),
    );
    const line = releases[0]?.types[0]?.changes[0];
    expect(line?.summary).toBe('add the releases view');
    expect(line?.featureNames).toEqual(['Help panel']);
    expect(line?.pr).toBe(845);
  });

  it('defaults a change with no release field to Unreleased', () => {
    const releases = groupFeaturesByRelease(
      payload({ changes: [{ date: '2026-09-26', type: 'added', features: [], summary: 'no release yet' }] }),
    );
    expect(releases[0]?.name).toBe('Unreleased');
  });

  it('dates a release by its newest visible change, ignoring internal ones', () => {
    const releases = groupFeaturesByRelease(
      payload({
        changes: [
          { date: '2026-09-02', type: 'fixed', features: [], summary: 'a fix', release: 'v1.0.0' },
          { date: '2026-09-05', type: 'added', features: [], summary: 'a feature', release: 'v1.0.0' },
          { date: '2026-09-09', type: 'internal', features: [], summary: 'refactor', release: 'v1.0.0' },
        ],
      }),
    );
    expect(releases[0]?.date).toBe('2026-09-05');
  });

  it('answers no releases at all for an empty catalog', () => {
    expect(groupFeaturesByRelease(payload())).toEqual([]);
  });
});
