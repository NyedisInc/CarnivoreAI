
export interface BudgetRequestRow {
  id: string;
  item_id: string;
  requested_micros: number;
  approved_micros: number | null;
  state: 'pending' | 'approved' | 'denied' | 'expired';
  decision_reason: string;
  created_at: number;
  decided_at: number | null;
}

export const MAX_ASK_MICROS = 1_000_000_000_000;
export const MAX_REASON_CHARS = 500;

export function parseDollars(text: string): number | null {
  const clean = text.trim().replace(/^\$/, '').replace(/,/g, '');
  const match = /^(\d+)(?:\.(\d{1,6}))?$/.exec(clean);
  if (!match) return null;
  const micros = Number(match[1]) * 1_000_000 + Number((match[2] ?? '').padEnd(6, '0'));
  return Number.isSafeInteger(micros) && micros > 0 && micros <= MAX_ASK_MICROS ? micros : null;
}

export function defaultAsk(capMicros: number | null | undefined, spentMicros?: number | null, held?: boolean): string {
  if (!held || typeof capMicros !== 'number' || typeof spentMicros !== 'number' || !Number.isFinite(capMicros) || !Number.isFinite(spentMicros)) return '';
  const over = spentMicros - capMicros;
  if (over <= 0 || over > MAX_ASK_MICROS) return '';
  const [whole, frac = ''] = (over / 1_000_000).toFixed(6).split('.');
  return `${whole}.${frac.replace(/0+$/, '').padEnd(2, '0')}`;
}

export function pendingFor(rows: readonly BudgetRequestRow[] | undefined, itemId: string): BudgetRequestRow | null {
  return rows?.find((r) => r.item_id === itemId && r.state === 'pending') ?? null;
}

export async function loadBudgetRequests(fetcher: (path: string) => Promise<unknown>): Promise<BudgetRequestRow[]> {
  const body = (await fetcher('/argent/budget/requests')) as { requests?: unknown } | null;
  return Array.isArray(body?.requests) ? (body!.requests as BudgetRequestRow[]) : [];
}
