import type { ChartConfig, QueryBody } from '../cells/analytics/types';
import { effectiveRange, seriesBody, treemapMetric, type PlanContext } from './plan';
import type { RankRow } from './shape';

export const FLOW_LEVELS = ['account_id', 'model', 'agent_kind', 'project'] as const;
export const FLOW_TOP = 3;
export const FLOW_MAX_QUERIES = (FLOW_LEVELS.length - 1) * (1 + FLOW_TOP);

function ranking(config: ChartConfig, ctx: PlanContext, level: string, drill?: Record<string, string>): QueryBody {
  const series = config.series.find((item) => item.visible !== false) ?? { metric: 'total_tokens' };
  const body = seriesBody(config, { ...series, metric: treemapMetric(config), operation: 'ranking', group_by: level }, effectiveRange(config, { ...ctx, marker: null }), ctx, 'ranking');
  return { ...body, filters: { ...body.filters, ...drill }, top_n: FLOW_TOP };
}

export function flowLevelsPlan(config: ChartConfig, ctx: PlanContext): QueryBody[] {
  return FLOW_LEVELS.slice(0, 3).map((level) => ranking(config, ctx, level));
}

export interface FlowDrill { level: number; key: string; filter: string }

export function flowDrills(levels: RankRow[][]): FlowDrill[] {
  return levels.slice(0, 3).flatMap((rows, level) => rows.filter((row) => row.filter_value && (row.value ?? 0) > 0 && row.key !== 'other')
    .slice(0, FLOW_TOP).map((row): FlowDrill => ({ level, key: row.key, filter: row.filter_value as string })));
}

export function flowLinksPlan(config: ChartConfig, ctx: PlanContext, drills: FlowDrill[]): QueryBody[] {
  return drills.map((drill) => ranking(config, ctx, FLOW_LEVELS[drill.level + 1] as string, { [FLOW_LEVELS[drill.level] as string]: drill.filter }));
}

export interface FlowNode { id: string; name: string; level: number }
export interface FlowLink { source: string; target: string; value: number }
export interface FlowGraph { nodes: FlowNode[]; links: FlowLink[] }

const idOf = (level: number, key: string): string => `${level}:${key}`;

export function flowGraph(levels: RankRow[][], drills: FlowDrill[], drilled: (RankRow[] | null)[], otherLabel: string): FlowGraph {
  const known: Set<string>[] = [new Set(), ...levels.slice(1, 3).map((rows) => new Set(rows.map((row) => row.key))), new Set()];
  const names = new Map<string, string>();
  for (const [level, rows] of levels.slice(0, 3).entries()) for (const row of rows) names.set(idOf(level, row.key), row.label);
  const projectTotals = new Map<string, number>();
  drills.forEach((drill, at) => {
    if (drill.level !== 2) return;
    for (const row of drilled[at] ?? []) if ((row.value ?? 0) > 0 && row.key !== 'other') projectTotals.set(row.key, (projectTotals.get(row.key) ?? 0) + (row.value as number));
  });
  known[3] = new Set([...projectTotals].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, FLOW_TOP).map(([key]) => key));
  const sums = new Map<string, FlowLink>();
  drills.forEach((drill, at) => {
    for (const row of drilled[at] ?? []) {
      if (row.value === null || row.value <= 0) continue;
      const level = drill.level + 1;
      const folded = row.key === 'other' || !known[level]!.has(row.key);
      const target = idOf(level, folded ? 'other' : row.key);
      names.set(target, folded ? otherLabel : row.label);
      const source = idOf(drill.level, drill.key);
      const link = sums.get(`${source}>${target}`);
      if (link) link.value += row.value; else sums.set(`${source}>${target}`, { source, target, value: row.value });
    }
  });
  const links = [...sums.values()];
  const used = new Set(links.flatMap((link) => [link.source, link.target]));
  const nodes = [...used].map((id): FlowNode => ({ id, name: names.get(id) ?? id, level: Number(id.split(':')[0]) }))
    .sort((a, b) => a.level - b.level || a.id.localeCompare(b.id));
  return { nodes, links };
}

export function flowDepth(graph: FlowGraph, levels: number): FlowGraph {
  const nodes = graph.nodes.filter((node) => node.level < levels);
  const ids = new Set(nodes.map((node) => node.id));
  return { nodes, links: graph.links.filter((link) => ids.has(link.source) && ids.has(link.target)) };
}
