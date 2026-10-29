import { describe, expect, test } from 'vitest';
import { FOLD_SCOPES_KEPT, foldScope, isFoldRecord, isSectionChoice, sectionIsOpen, withFold, withoutScopes } from './state';

describe('the fold record', () => {
  test('opens and closes a folder per scope, and drops an emptied scope', () => {
    const open = withFold({}, foldScope('workdir', '/a'), 'src', true);
    expect(open).toEqual({ 'project:/a': ['src'] });
    expect(withFold(open, 'project:/a', 'src', false)).toEqual({});
  });

  test('keeps at most the newest project scopes, and the global scope always', () => {
    let record = withFold({}, 'user', 'skills', true);
    for (let i = 0; i <= FOLD_SCOPES_KEPT; i += 1) record = withFold(record, `project:/p${i}`, 'src', true);
    expect(Object.keys(record).filter((key) => key !== 'user')).toHaveLength(FOLD_SCOPES_KEPT);
    expect(record['project:/p0']).toBeUndefined();
    expect(record['user']).toEqual(['skills']);
    expect(isFoldRecord(record)).toBe(true);
  });

  test('collapse closes only the scopes named', () => {
    expect(withoutScopes({ user: ['a'], 'project:/x': ['b'], 'project:/y': ['c'] }, ['user', 'project:/x'])).toEqual({ 'project:/y': ['c'] });
  });
});

describe('a stored value that does not fit reads as absent', () => {
  test('a malformed fold record or section choice is refused', () => {
    expect(isFoldRecord(['src'])).toBe(false);
    expect(isFoldRecord({ user: [1] })).toBe(false);
    expect(isSectionChoice({ workdir: 'yes' })).toBe(false);
    expect(isSectionChoice({ other: true })).toBe(false);
    expect(isSectionChoice({ user: true })).toBe(true);
  });

  test('sections default to the project open, and the global folder open only with no project', () => {
    expect(sectionIsOpen({}, 'workdir', true)).toBe(true);
    expect(sectionIsOpen({}, 'user', true)).toBe(false);
    expect(sectionIsOpen({}, 'user', false)).toBe(true);
    expect(sectionIsOpen({ user: true }, 'user', true)).toBe(true);
  });
});
