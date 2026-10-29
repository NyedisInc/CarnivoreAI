import type { GroupDetail, QueryResult } from '../cells/analytics/types';
import { t } from '../../lib/i18n/index.svelte';

export type RankRow = NonNullable<QueryResult['ranking']>[number];

export interface BoardRow { key: string; label: string; value: number | null; share: number; spark: (number | null)[]; hint: string }

export function rowHint(label: string, detail?: GroupDetail): string {
  if (!detail || detail.count === 0) return label;
  const names = detail.folders.join(', ');
  const gone = detail.unnamed > 0 ? t('viz.folders_gone', { count: detail.unnamed }) : '';
  const list = [names, gone].filter(Boolean).join(names && gone ? t('viz.folders_and') : '');
  return t('viz.folders_hint', { label, list });
}

export function leaderboardRows(ranking: RankRow[] | null | undefined, timeline: QueryResult | null, topN: number,
  plot: (point: { time: string; value: number | null }, points: readonly { time: string }[]) => number | null = (point) => point.value): BoardRow[] {
  const rows = (ranking ?? []).slice(0, Math.max(0, topN));
  const peak = Math.max(0, ...rows.map((row) => row.value ?? 0));
  return rows.map((row) => ({
    key: row.key,
    label: row.label,
    value: row.value,
    share: peak > 0 && row.value !== null && row.value > 0 ? row.value / peak : 0,
    spark: (timeline?.series.find((item) => item.key === row.key)?.points ?? []).map((point, _at, points) => plot(point, points)),
    hint: rowHint(row.label, row.detail),
  }));
}

export interface TreeNode { name: string; value: number; children?: TreeNode[] }

export interface ProviderModels { provider: string; models: RankRow[]; projects: Record<string, RankRow[]> }

function leaves(rows: RankRow[]): TreeNode[] {
  return rows.filter((row) => row.value !== null && row.value > 0).map((row) => ({ name: row.label, value: row.value as number }));
}

export function treemapTree(input: ProviderModels[], otherLabel: string): TreeNode[] {
  const tree: TreeNode[] = [];
  for (const provider of input) {
    const models: TreeNode[] = [];
    for (const model of provider.models) {
      if (model.value === null || model.value <= 0) continue;
      const drilled = model.filter_value ? leaves(provider.projects[model.filter_value] ?? []) : [];
      if (!drilled.length) { models.push({ name: model.label, value: model.value }); continue; }
      const rest = model.value - drilled.reduce((sum, leaf) => sum + leaf.value, 0);
      models.push({ name: model.label, value: model.value, children: rest > 0 ? [...drilled, { name: otherLabel, value: rest }] : drilled });
    }
    if (models.length) tree.push({ name: provider.provider, value: models.reduce((sum, node) => sum + node.value, 0), children: models });
  }
  return tree;
}

export interface HeatCell { hour: number; weekday: number; value: number | null }

export function heatMatrix(points: { time: string; value: number | null }[]): { cells: HeatCell[]; max: number | null } {
  const sums = new Array<number>(168).fill(0);
  const counts = new Array<number>(168).fill(0);
  for (const point of points) {
    const at = /^(\d{4})-(\d{2})-(\d{2})T(\d{2})/.exec(point.time);
    if (!at || point.value === null || !Number.isFinite(point.value)) continue;
    const weekday = (new Date(Date.UTC(Number(at[1]), Number(at[2]) - 1, Number(at[3]))).getUTCDay() + 6) % 7;
    const slot = weekday * 24 + Number(at[4]);
    sums[slot] = (sums[slot] as number) + point.value;
    counts[slot] = (counts[slot] as number) + 1;
  }
  const cells = sums.map((sum, slot): HeatCell => ({ hour: slot % 24, weekday: Math.floor(slot / 24), value: counts[slot] ? sum / (counts[slot] as number) : null }));
  const known = cells.map((cell) => cell.value).filter((value): value is number => value !== null);
  return { cells, max: known.length ? Math.max(...known) : null };
}

export function treemapDepth(tree: TreeNode[], depth: number): TreeNode[] {
  return tree.map((node) => (node.children && depth > 1 ? { ...node, children: treemapDepth(node.children, depth - 1) } : { name: node.name, value: node.value }));
}
