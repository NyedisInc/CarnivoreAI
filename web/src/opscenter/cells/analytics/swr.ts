import type { DimensionItem, QueryBody } from './types';

export function planShape(bodies: QueryBody[], contextMetrics: string[]): string {
  return JSON.stringify({
    contextMetrics,
    bodies: bodies.map(({ from: _from, to: _to, comparison: _comparison, ...rest }) => rest),
  });
}

export function holdWhileRefreshing<T>(previousShape: string | null, nextShape: string, held: T, empty: T): T {
  return previousShape !== null && previousShape === nextShape ? held : empty;
}

export function mergeDimensions(
  previous: Record<string, DimensionItem[]>,
  names: string[],
  settled: PromiseSettledResult<DimensionItem[]>[],
): Record<string, DimensionItem[]> {
  return Object.fromEntries(names.map((name, index) => {
    const entry = settled[index];
    return [name, entry?.status === 'fulfilled' ? entry.value : previous[name] ?? []];
  }));
}
