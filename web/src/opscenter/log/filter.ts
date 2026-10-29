import { LOG_LEVELS, type LogLevel, type LogRecord } from './types';

export const SESSION_KEYS = ['session', 'session_id', 'session_uuid', 'session_name', 'tmux_name', 'tmux_session'] as const;

export interface FieldChip {
  key: string;
  value: string;
  exclude: boolean;
}

export interface LogFilter {
  levels: LogLevel[];
  hiddenSources: string[];
  session: string;
  text: string;
  fields: FieldChip[];
}

export interface CompiledFilter {
  match: (record: LogRecord) => boolean;
  error: string | null;
  empty: boolean;
}

export function emptyFilter(levels: readonly LogLevel[] = LOG_LEVELS): LogFilter {
  return { levels: [...levels], hiddenSources: [], session: '', text: '', fields: [] };
}

export function recordText(record: LogRecord): string {
  const pairs = Object.entries(record.fields).map(([k, v]) => `${k}=${v}`);
  return [record.event, ...pairs, ...record.lines].join('\n');
}

export function compileText(text: string): { test: (haystack: string) => boolean; error: string | null } {
  const query = text.trim();
  if (!query) return { test: () => true, error: null };
  const pattern = /^\/(.+)\/([a-z]*)$/.exec(query);
  if (pattern) {
    try {
      const re = new RegExp(pattern[1] as string, pattern[2] as string);
      return { test: (haystack) => { re.lastIndex = 0; return re.test(haystack); }, error: null };
    } catch (error) {
      return { test: () => false, error: error instanceof Error ? error.message : String(error) };
    }
  }
  const needle = query.toLowerCase();
  return { test: (haystack) => haystack.toLowerCase().includes(needle), error: null };
}

export function sessionOf(record: LogRecord): string | null {
  for (const key of SESSION_KEYS) {
    const value = record.fields[key];
    if (value) return value;
  }
  return null;
}

export function compile(filter: LogFilter): CompiledFilter {
  const levels = new Set(filter.levels);
  const hidden = new Set(filter.hiddenSources);
  const session = filter.session.trim().toLowerCase();
  const text = compileText(filter.text);
  const hasText = filter.text.trim() !== '';
  const fields = filter.fields;
  const empty = levels.size === LOG_LEVELS.length && hidden.size === 0 && !session && !hasText && fields.length === 0;
  const match = (record: LogRecord): boolean => {
    if (!levels.has(record.level) || hidden.has(record.source)) return false;
    if (session && !SESSION_KEYS.some((key) => (record.fields[key] ?? '').toLowerCase().includes(session))) return false;
    for (const chip of fields) {
      if ((record.fields[chip.key] === chip.value) === chip.exclude) return false;
    }
    return !hasText || text.test(recordText(record));
  };
  return { match, error: text.error, empty };
}

export function toggleField(filter: LogFilter, key: string, value: string, exclude: boolean): LogFilter {
  const at = filter.fields.findIndex((c) => c.key === key && c.value === value);
  const fields = [...filter.fields];
  if (at < 0) fields.push({ key, value, exclude });
  else if (fields[at]?.exclude === exclude) fields.splice(at, 1);
  else fields[at] = { key, value, exclude };
  return { ...filter, fields };
}

export function removeField(filter: LogFilter, index: number): LogFilter {
  return { ...filter, fields: filter.fields.filter((_, i) => i !== index) };
}

export function toggleIn<T>(list: readonly T[], item: T): T[] {
  return list.includes(item) ? list.filter((x) => x !== item) : [...list, item];
}

export function sourcesOf(records: readonly LogRecord[]): string[] {
  const counts = new Map<string, number>();
  for (const record of records) counts.set(record.source, (counts.get(record.source) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([source]) => source);
}
