
import type { RouteAnswer, RouteTable } from './types';

export const STRETCH_KEYS: ReadonlySet<string> = new Set([
  'label', 'description', 'name', 'session_name', 'project', 'project_name', 'model_label', 'question', 'body',
  'summary', 'detail', 'title', 'display_name', 'message', 'text', 'cwd_display', 'git_branch', 'first_prompt',
  'model_display_name', 'note', 'reason',
]);

export const COUNT_KEYS: ReadonlySet<string> = new Set([
  'count', 'total', 'n', 'conversations', 'tokens', 'total_tokens', 'input_tokens', 'output_tokens', 'events',
  'rows', 'done', 'queued', 'log_lines', 'total_commands', 'iterations', 'sessions', 'runs', 'calls', 'messages',
  'nano_usd', 'contributing_conversations',
]);

export const IDENTITY_KEYS: readonly string[] = [
  'id', 'session_id', 'uuid', 'session_uuid', 'key', 'name', 'tmux', 'tmux_session', 'session_name', 'path', 'root', 'working_dir', 'cwd',
];

export const LONG_TAIL = ' with an unusually long name that keeps going';
export const BIG = 4321;
export const MANY_ROWS = 36;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

const GROUPING_KEYS: readonly string[] = ['agent', 'model', 'host', 'tool', 'skill', 'plugin', 'label', 'project', 'title', 'metric'];

const UNIQUE_DEPTH = 2;

function uniqueCopy(row: Record<string, unknown>, copy: number, depth = UNIQUE_DEPTH): Record<string, unknown> {
  const out: Record<string, unknown> = { ...row };
  for (const key of [...IDENTITY_KEYS, ...GROUPING_KEYS]) {
    const value = out[key];
    if (typeof value === 'string') out[key] = `${value}-c${copy}`;
    else if (typeof value === 'number') out[key] = value + copy * 1_000_000;
  }
  if (depth > 0) {
    for (const [key, value] of Object.entries(out)) if (isRecord(value)) out[key] = uniqueCopy(value, copy, depth - 1);
  }
  return out;
}

function manyRows(list: unknown[]): unknown[] {
  if (list.length === 0 || !list.every(isRecord) || !IDENTITY_KEYS.some((key) => key in (list[0] as Record<string, unknown>))) return list;
  const out: unknown[] = [...list];
  for (let copy = 1; out.length < MANY_ROWS; copy += 1) {
    for (const row of list) if (out.length < MANY_ROWS) out.push(uniqueCopy(row as Record<string, unknown>, copy));
  }
  return out;
}

export function stressValue(value: unknown, key = ''): unknown {
  if (typeof value === 'string') return STRETCH_KEYS.has(key) && value.trim() ? `${value}${LONG_TAIL}` : value;
  if (typeof value === 'number') return COUNT_KEYS.has(key) && Number.isFinite(value) ? value * BIG : value;
  if (Array.isArray(value)) return manyRows(value).map((item) => stressValue(item, key));
  if (isRecord(value)) {
    const out: Record<string, unknown> = {};
    for (const [inner, item] of Object.entries(value)) out[inner] = stressValue(item, inner);
    return out;
  }
  return value;
}

function stressAnswer(answer: RouteAnswer): RouteAnswer {
  if (typeof answer !== 'function') return stressValue(answer);
  const call = answer as (url: URL, init?: RequestInit) => unknown;
  return (url: URL, init?: RequestInit) => stressValue(call(url, init));
}

export function stressTable(table: RouteTable): RouteTable {
  return Object.fromEntries(Object.entries(table).map(([route, answer]) => [route, stressAnswer(answer)]));
}
