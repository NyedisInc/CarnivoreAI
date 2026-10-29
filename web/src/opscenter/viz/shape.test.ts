import { describe, expect, it, test } from 'vitest';
import { heatMatrix, leaderboardRows, treemapDepth, treemapTree, type ProviderModels, type RankRow } from './shape';
import type { QueryResult } from '../cells/analytics/types';

const rank = (key: string, value: number | null, filter_value: string | null = key): RankRow => ({ key, label: key.toUpperCase(), value, filter_value });

describe('leaderboardRows', () => {
  test('caps at topN, scales bars to the largest row and matches sparklines on key', () => {
    const timeline = { series: [{ key: 'a', label: 'A', points: [{ time: 't1', value: 1 }, { time: 't2', value: null }] }] } as unknown as QueryResult;
    const rows = leaderboardRows([rank('a', 8), rank('b', 2), rank('c', 1)], timeline, 2);
    expect(rows.map((row) => row.key)).toEqual(['a', 'b']);
    expect(rows.map((row) => row.share)).toEqual([1, 0.25]);
    expect(rows[0]!.spark).toEqual([1, null]);
    expect(rows[1]!.spark).toEqual([]);
  });

  test('an unknown or zero value has no bar and empty input is an empty table', () => {
    expect(leaderboardRows([rank('a', null), rank('b', 0)], null, 5).map((row) => row.share)).toEqual([0, 0]);
    expect(leaderboardRows(null, null, 5)).toEqual([]);
  });
});

describe('treemapTree', () => {
  const input: ProviderModels[] = [
    { provider: 'claude', models: [rank('opus', 10), rank('haiku', 4), rank('other', 3, null)], projects: { opus: [rank('p1', 6), rank('p2', 1)], haiku: [] } },
    { provider: 'codex', models: [], projects: {} },
  ];

  test('folds provider > model > project and keeps every model area equal to its ranked value', () => {
    const tree = treemapTree(input, 'rest');
    expect(tree).toHaveLength(1);
    expect(tree[0]).toMatchObject({ name: 'claude', value: 17 });
    const opus = tree[0]!.children!.find((node) => node.name === 'OPUS')!;
    expect(opus.children!.map((node) => [node.name, node.value])).toEqual([['P1', 6], ['P2', 1], ['rest', 3]]);
    expect(opus.children!.reduce((sum, node) => sum + node.value, 0)).toBe(opus.value);
  });

  test('a model with no drill, or a null filter value, stays a leaf; empty providers drop out', () => {
    const models = treemapTree(input, 'rest')[0]!.children!;
    expect(models.find((node) => node.name === 'HAIKU')!.children).toBeUndefined();
    expect(models.find((node) => node.name === 'OTHER')!.children).toBeUndefined();
  });

  test('treemapDepth cuts levels and keeps values', () => {
    const tree = treemapTree(input, 'rest');
    expect(treemapDepth(tree, 1)).toEqual([{ name: 'claude', value: 17 }]);
    expect(treemapDepth(tree, 2)[0]!.children!.every((node) => node.children === undefined)).toBe(true);
    expect(treemapDepth(tree, 3)[0]!.children![0]!.children).toBeDefined();
  });
});

describe('heatMatrix', () => {
  test('folds local hourly stamps into weekday by hour and averages what lands together', () => {
    const { cells, max } = heatMatrix([
      { time: '2024-01-01T09:00:00+00:00', value: 2 }, { time: '2024-01-08T09:00:00+00:00', value: 4 },
      { time: '2024-01-07T23:00:00-05:00', value: 10 }, { time: '2024-01-02T00:00:00+00:00', value: null },
    ]);
    expect(cells).toHaveLength(168);
    expect(cells.find((cell) => cell.weekday === 0 && cell.hour === 9)!.value).toBe(3);
    expect(cells.find((cell) => cell.weekday === 6 && cell.hour === 23)!.value).toBe(10);
    expect(cells.find((cell) => cell.weekday === 1 && cell.hour === 0)!.value).toBeNull();
    expect(max).toBe(10);
  });

  test('no known bucket means no maximum and every cell unknown, never zero', () => {
    const empty = heatMatrix([{ time: 'garbage', value: 5 }]);
    expect(empty.max).toBeNull();
    expect(empty.cells.every((cell) => cell.value === null)).toBe(true);
  });
});

describe('rowHint (#1157: a folded bucket names its folders, never a raw id)', () => {
  it('lists the folder names and counts the ones no longer on disk', async () => {
    const { rowHint } = await import('./shape');
    expect(rowHint('Carnivore')).toBe('Carnivore');
    expect(rowHint('2 folders outside projects', { count: 2, folders: ['scratch'], unnamed: 1 }))
      .toBe('2 folders outside projects: scratch, and 1 no longer on disk');
    expect(rowHint('1 folder outside projects', { count: 1, folders: [], unnamed: 1 }))
      .toBe('1 folder outside projects: 1 no longer on disk');
  });
});
