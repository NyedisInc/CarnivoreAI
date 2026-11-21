import type { TreeGroup } from './lab-model';

export const TREE_FOLDS_KEY = 'devwidgetlab.tree.folds';

export type TreeFolds = Record<string, boolean>;

export function readTreeFolds(): TreeFolds {
  try {
    const parsed: unknown = JSON.parse(globalThis.localStorage?.getItem(TREE_FOLDS_KEY) ?? 'null');
    if (typeof parsed !== 'object' || parsed === null) return {};
    return Object.fromEntries(Object.entries(parsed).filter((entry): entry is [string, boolean] => typeof entry[1] === 'boolean'));
  } catch (error) {
    console.warn('[widget lab] tree folds unreadable', error);
    return {};
  }
}

export function writeTreeFolds(folds: TreeFolds): void {
  try {
    globalThis.localStorage?.setItem(TREE_FOLDS_KEY, JSON.stringify(folds));
  } catch (error) {
    console.warn('[widget lab] tree folds not stored', error);
  }
}

export function groupOpen(group: TreeGroup, folds: TreeFolds, picked: string, filtering: boolean): boolean {
  return filtering || (folds[group.id] ?? (group.open === true || group.leaves.some((leaf) => leaf.key === picked)));
}

export const ROOT_FOLD = '*widgets';

export function rootOpen(folds: TreeFolds, filtering: boolean): boolean {
  return filtering || (folds[ROOT_FOLD] ?? true);
}

export function foldAll(groups: readonly TreeGroup[], open: boolean): TreeFolds {
  return { [ROOT_FOLD]: open, ...Object.fromEntries(groups.map((group) => [group.id, open])) };
}
