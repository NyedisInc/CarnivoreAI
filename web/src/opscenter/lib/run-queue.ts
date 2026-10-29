
export interface ActivityRow {
  id: string;
  name: string;
  area: string;
  time: string;
  tone?: 'wait';
}

export const QUEUE_SHOWN = 8;

export interface Capped<T> {
  shown: T[];
  more: number;
}

export function cap<T>(rows: readonly T[], total: number = rows.length, limit: number = QUEUE_SHOWN): Capped<T> {
  const shown = rows.slice(0, Math.max(0, limit));
  return { shown, more: Math.max(0, Math.max(total, rows.length) - shown.length) };
}
