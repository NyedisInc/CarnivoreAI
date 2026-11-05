import { RAIL_CUT_EPSILON, RAIL_MIN_SHARE } from './rail-model';

export function round3(value: number): number {
  return Math.round(value * 1000) / 1000;
}

export function evenCuts(count: number): number[] {
  return Array.from({ length: Math.max(0, count - 1) }, (_, i) => round3((i + 1) / count));
}

export function edgesOf(cuts: readonly number[]): number[] {
  return [0, ...cuts, 1];
}

export function spanOf(cuts: readonly number[], section: number): [number, number] {
  const edges = edgesOf(cuts);
  return [edges[section] ?? 0, edges[section + 1] ?? 1];
}

export function validCuts(raw: unknown, count: number): raw is number[] {
  if (!Array.isArray(raw) || raw.length !== count - 1 || raw.some((cut) => typeof cut !== 'number' || !Number.isFinite(cut))) return false;
  const edges = edgesOf(raw as number[]);
  return edges.every((edge, i) => i === 0 || edge - edges[i - 1]! >= RAIL_MIN_SHARE - RAIL_CUT_EPSILON);
}

export function repairCuts(raw: unknown, count: number): number[] {
  return validCuts(raw, count) ? raw.map(round3) : evenCuts(count);
}

function middleOf(cuts: readonly number[], section: number): number {
  const [start, end] = spanOf(cuts, section);
  return round3(start + (end - start) / 2);
}

export function canHalve(cuts: readonly number[], section: number): boolean {
  const [start, end] = spanOf(cuts, section);
  const mid = middleOf(cuts, section);
  return mid - start >= RAIL_MIN_SHARE - RAIL_CUT_EPSILON && end - mid >= RAIL_MIN_SHARE - RAIL_CUT_EPSILON;
}

export function halveAt(cuts: readonly number[], section: number): number[] {
  const next = [...cuts];
  next.splice(section, 0, middleOf(cuts, section));
  return next;
}

export function dropCut(cuts: readonly number[], removed: number): number[] {
  if (cuts.length === 0) return [];
  const gone = removed === 0 ? 0 : removed - 1;
  return cuts.filter((_, i) => i !== gone);
}

export function cutBounds(cuts: readonly number[], index: number): { min: number; max: number } {
  const edges = edgesOf(cuts);
  return { min: round3(edges[index]! + RAIL_MIN_SHARE), max: round3(edges[index + 2]! - RAIL_MIN_SHARE) };
}

export function moveCut(cuts: readonly number[], index: number, value: number): number[] {
  const { min, max } = cutBounds(cuts, index);
  const next = [...cuts];
  next[index] = round3(Math.min(max, Math.max(min, value)));
  return next;
}

export function percent(fraction: number): string {
  return `${Math.round(fraction * 1000) / 10}%`;
}

export function sectionStyle(axis: 'x' | 'y', section: number, cuts: readonly number[]): string {
  const [from, to, a, b] = axis === 'y' ? ['top', 'bottom', 'left', 'right'] : ['left', 'right', 'top', 'bottom'];
  const [start, end] = spanOf(cuts, section);
  const head = start <= 0 ? '0' : percent(start);
  const tail = end >= 1 ? '0' : `calc(100% - ${percent(end)})`;
  return `${from}: ${head}; ${to}: ${tail}; ${a}: 0; ${b}: 0`;
}

export function panelCuts(cuts: readonly number[], shown: readonly number[]): number[] {
  return shown.slice(0, -1).map((section) => cuts[section] ?? 0.5);
}

export function centreOf(cuts: readonly number[], index: number): number {
  const edges = edgesOf(cuts);
  return round3(((edges[index] ?? 0) + (edges[index + 2] ?? 1)) / 2);
}
