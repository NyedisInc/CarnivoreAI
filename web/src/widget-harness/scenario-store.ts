
import type { RouteTable } from '../opscenter/widgets/fixtures/types';

export interface Simulated {
  status: number;
  body: unknown;
}

const WRITE_METHODS: ReadonlySet<string> = new Set(['PUT', 'PATCH', 'POST']);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function bodyRecord(init: RequestInit | undefined): Record<string, unknown> | null {
  if (typeof init?.body !== 'string') return null;
  try {
    const parsed: unknown = JSON.parse(init.body);
    return isRecord(parsed) ? parsed : null;
  } catch (error) {
    console.warn('[widget harness] a write body was not json', error);
    return null;
  }
}

export class ScenarioStore {
  readonly table: RouteTable;
  #reads = new Map<string, unknown>();

  constructor(table: RouteTable) {
    this.table = table;
    for (const [key, answer] of Object.entries(table)) {
      if (key.startsWith('GET ') && !key.endsWith('*') && typeof answer !== 'function') this.#reads.set(key.slice(4), structuredClone(answer));
    }
  }

  simulate(method: string, path: string, init?: RequestInit): Simulated | undefined {
    if (method === 'GET') return this.#reads.has(path) ? { status: 200, body: structuredClone(this.#reads.get(path)) } : undefined;
    if (!WRITE_METHODS.has(method) || `${method} ${path}` in this.table) return undefined;
    const current = this.#reads.get(path);
    const incoming = bodyRecord(init);
    if (!isRecord(current) || !incoming) return undefined;
    if ('expected_revision' in incoming && 'revision' in current && incoming['expected_revision'] !== current['revision']) {
      return { status: 409, body: structuredClone(current) };
    }
    const next: Record<string, unknown> = { ...current };
    for (const [field, value] of Object.entries(incoming)) if (field in current && field !== 'revision') next[field] = value;
    if (typeof current['revision'] === 'number') next['revision'] = current['revision'] + 1;
    if ('updated_at' in current) next['updated_at'] = new Date().toISOString();
    this.#reads.set(path, next);
    return { status: 200, body: structuredClone(next) };
  }
}
