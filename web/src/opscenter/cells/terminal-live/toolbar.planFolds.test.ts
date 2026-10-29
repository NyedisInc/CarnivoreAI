import { expect, test } from 'vitest';
import { planFolds, splitToolbar, TOOLBAR_ITEMS, type FoldCandidate } from './toolbar';

const item = (id: string, active = false, width = 28): FoldCandidate => ({ id, width, active });
const bar = (active: string[] = []): FoldCandidate[] =>
  ['search', 'sleep', 'utilities', 'size-master'].map((id) => item(id, active.includes(id)));

test('nothing folds while the toolbar fits beside the natural tabs', () => {
  expect(planFolds(28 + 4 * 28, 28, bar())).toEqual([]);
});

test('inactive icons fold first, least important first, and active ones are kept', () => {
  const folded = planFolds(28 + 2 * 28, 28, bar(['utilities', 'size-master']));
  expect(folded).toEqual(['sleep', 'search']);
  expect(folded).not.toContain('utilities');
  expect(folded).not.toContain('size-master');
});

test('active icons fold only once every inactive one is gone, and only as many as needed', () => {
  expect(planFolds(28 + 28, 28, bar(['utilities', 'size-master']))).toEqual(
    ['sleep', 'search', 'utilities']);
});

test('with no room beyond the kebab everything folds and the rest is the tabs shrinking', () => {
  expect(planFolds(10, 28, bar(['utilities'])).length).toBe(4);
});

test('an item that draws nothing is never a fold candidate', () => {
  expect(planFolds(28, 28, [item('utilities', false, 0), item('files')])).toEqual(['files']);
});

test('files, notes, theme, skills, plugins and the background picture are bar items again, each folding at its own rung', () => {
  const ids = TOOLBAR_ITEMS.map((i) => i.id);
  for (const id of ['skills', 'plugins', 'files', 'notes', 'theme', 'background']) expect(ids).toContain(id);
  for (const width of [0, 200, 300, 340, 380, 420, 460, 500, 800, 1600]) {
    const split = splitToolbar(width);
    expect([...split.bar, ...split.overflow].map((i) => i.id).sort()).toEqual([...ids].sort());
  }
  expect(splitToolbar(459).bar.map((i) => i.id)).not.toContain('size-master');
  expect(splitToolbar(460).bar.map((i) => i.id)).toContain('size-master');
});
