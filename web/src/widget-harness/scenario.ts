
import type { RouteTable } from '../opscenter/widgets/fixtures/types';

const ROUTE_KEY = /^(GET|POST|PUT|PATCH|DELETE) \/\S*$/;

export const MAX_SCENARIO_CHARS = 1_000_000;

export interface ScenarioOk {
  ok: true;
  table: RouteTable;
  routes: number;
}

export interface ScenarioError {
  ok: false;
  error: string;
}

export type ScenarioResult = ScenarioOk | ScenarioError;

export function parseScenario(text: string): ScenarioResult {
  if (text.trim() === '') return { ok: false, error: 'the box is empty' };
  if (text.length > MAX_SCENARIO_CHARS) return { ok: false, error: `the text is longer than ${MAX_SCENARIO_CHARS} characters` };
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    return { ok: false, error: `this is not valid json: ${reason}` };
  }
  if (typeof value !== 'object' || value === null || Array.isArray(value)) {
    return { ok: false, error: 'a scenario is one json object whose keys are routes, like "GET /sessions/list"' };
  }
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return { ok: false, error: 'the scenario has no routes' };
  for (const [key] of entries) {
    if (!ROUTE_KEY.test(key)) {
      return { ok: false, error: `"${key}" is not a route: write a method, a space and a path, like "GET /sessions/list"` };
    }
  }
  return { ok: true, table: Object.fromEntries(entries), routes: entries.length };
}

export function overlayScenario(base: RouteTable, scenario: RouteTable): RouteTable {
  return { ...base, ...scenario };
}

export function tableToJson(table: RouteTable): string {
  const plain = Object.fromEntries(Object.entries(table).filter(([, answer]) => typeof answer !== 'function'));
  return JSON.stringify(plain, null, 2);
}

export function unusedScenarioReads(scenario: RouteTable, asked: readonly string[]): string[] {
  return Object.keys(scenario).filter((key) => key.startsWith('GET ') && !key.endsWith('*') && !asked.includes(key));
}
