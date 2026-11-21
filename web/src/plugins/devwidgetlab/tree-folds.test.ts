/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import type { TreeGroup } from './lab-model';
import { foldAll, groupOpen, readTreeFolds, ROOT_FOLD, rootOpen, TREE_FOLDS_KEY, writeTreeFolds } from './tree-folds';

const group = (id: string, keys: string[] = []): TreeGroup => ({ id, label: id, leaves: keys.map((key) => ({ key, label: key })) });

afterEach(() => localStorage.clear());

describe('the top-level fold', () => {
  it('is open until the person shuts it, and always open while a filter is on', () => {
    expect(rootOpen({}, false)).toBe(true);
    expect(rootOpen({ [ROOT_FOLD]: false }, false)).toBe(false);
    expect(rootOpen({ [ROOT_FOLD]: false }, true)).toBe(true);
  });

  it('is never a group id, so a group cannot shadow it', () => {
    expect(ROOT_FOLD.startsWith('*')).toBe(true);
  });
});

describe('fold all', () => {
  it('sets the top-level fold and every group to one state', () => {
    const groups = [group('overview'), group('tools')];
    expect(foldAll(groups, false)).toEqual({ [ROOT_FOLD]: false, overview: false, tools: false });
    expect(foldAll(groups, true)).toEqual({ [ROOT_FOLD]: true, overview: true, tools: true });
  });

  it('overrides "holds the picked widget": after a fold all, a group holding the pick is shut too', () => {
    const picked = group('overview', ['core.notes']);
    expect(groupOpen(picked, {}, 'core.notes', false)).toBe(true);
    expect(groupOpen(picked, foldAll([picked], false), 'core.notes', false)).toBe(false);
  });
});

describe('stored folds', () => {
  it('reads back what was written, and reads junk as nothing stored', () => {
    writeTreeFolds({ [ROOT_FOLD]: false, tools: true });
    expect(readTreeFolds()).toEqual({ [ROOT_FOLD]: false, tools: true });
    localStorage.setItem(TREE_FOLDS_KEY, '{"tools":"yes","overview":false}');
    expect(readTreeFolds()).toEqual({ overview: false });
    localStorage.setItem(TREE_FOLDS_KEY, 'not json');
    expect(readTreeFolds()).toEqual({});
  });
});
