
export type FixtureKind = 'data' | 'empty' | 'stress';

export const FIXTURE_KINDS: readonly FixtureKind[] = ['data', 'empty'];

export type RouteAnswer = unknown | ((url: URL, init?: RequestInit) => unknown);

export type RouteTable = Readonly<Record<string, RouteAnswer>>;

export interface WidgetFixtures {
  data: RouteTable;
  empty: RouteTable;
}
