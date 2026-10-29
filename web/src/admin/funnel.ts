import type { AdminApi } from './admin.js';

export const NEWS_EXPORT_PATH = '/users/news-export';

export type StepCounts = Record<string, Record<string, number>>;

export interface FunnelDay {
    date: string;
    start: StepCounts;
    proof: StepCounts;
    done: StepCounts;
}

export const FUNNEL_STEPS = ['start', 'proof', 'done'] as const;
export type FunnelStep = (typeof FUNNEL_STEPS)[number];

export interface TotalRow {
    source: string;
    provider: string;
    start: number;
    proof: number;
    done: number;
}

export async function funnelDays(api: AdminApi, days: number): Promise<FunnelDay[]> {
    const body = (await api.call('GET', '/funnel?days=' + days, null, true)) as Record<string, unknown> | null;
    const rows = Array.isArray(body?.days) ? (body?.days as Partial<FunnelDay>[]) : [];
    return rows.map((r) => ({
        date: String(r.date ?? ''),
        start: r.start ?? {},
        proof: r.proof ?? {},
        done: r.done ?? {},
    }));
}

export function stepTotal(counts: StepCounts): number {
    let sum = 0;
    for (const providers of Object.values(counts)) {
        for (const n of Object.values(providers)) sum += Number(n) || 0;
    }
    return sum;
}

export function totalsBySource(days: FunnelDay[]): TotalRow[] {
    const rows = new Map<string, TotalRow>();
    for (const day of days) {
        for (const step of FUNNEL_STEPS) {
            for (const [source, providers] of Object.entries(day[step])) {
                for (const [provider, n] of Object.entries(providers)) {
                    const key = source + '\u0000' + provider;
                    const row = rows.get(key) ?? { source, provider, start: 0, proof: 0, done: 0 };
                    row[step] += Number(n) || 0;
                    rows.set(key, row);
                }
            }
        }
    }
    return [...rows.values()].sort(
        (a, b) => a.source.localeCompare(b.source) || a.provider.localeCompare(b.provider),
    );
}

export async function exportNewsList(api: AdminApi, doc: Document): Promise<void> {
    const csv = await api.callText(NEWS_EXPORT_PATH);
    const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    const link = doc.createElement('a');
    link.href = url;
    link.download = 'carnivore-news-list.csv';
    doc.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}
